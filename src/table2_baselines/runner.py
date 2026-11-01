import collections,contextlib,csv,datetime,fcntl,hashlib,io,json,os,socket,subprocess,time
from pathlib import Path
from .registry import ROOT,METHODS
from .common import public_task,project_path,canonical,sha,coverage,now,write_json,InfrastructureError
from secthinker_experiments.artifacts import slug

def source_fingerprint():
    paths=[]
    for package in ['table2_baselines','prompt_baselines','secthinker_evaluation','secthinker_experiments','seccoder_baseline','securecoder_baseline','rescue_baseline','codexity_baseline','autosafecoder_prepared']:
        paths.extend((ROOT/'src'/package).glob('*.py'))
    paths.extend((ROOT/'baseline/INDICT').glob('*.py'))
    paths.extend((ROOT/'baseline/RESCUE/src').rglob('*.py'))
    paths.extend((ROOT/'config').glob('*/requirements*.resolved.txt'))
    index=ROOT/'tools/table2/rootfs-index.json'
    if index.exists():paths.append(index)
    return {str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in sorted(set(paths))}

@contextlib.contextmanager
def lock(output,name):
    with (output/('.'+name+'.lock')).open('a+') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as e:raise InfrastructureError('Output already locked for '+name) from e
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)

def new_output(dataset,method,model,n):
    stamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%dT%H%M%S%f')
    out=ROOT/'output'/dataset/f'{slug(model)}_{slug(method)}_n{n}_{stamp}'
    out.mkdir(parents=True,exist_ok=False);return out

def _manifest(output,dataset,method,config,ts,validation_only=False):
    out=project_path(output);out.mkdir(parents=True,exist_ok=True)
    if validation_only and not out.is_relative_to(ROOT/'runs/_setup/table2_2026-10-31'):raise ValueError('Validation outputs must stay in setup directory')
    for t in ts:public_task(t)
    cfg={'dataset':dataset,'method':method,'model':config['models']['generation']['model'],'method_config':config,'task_input_sha256':sha(canonical(ts)),'source_sha256':source_fingerprint(),'validation_only':validation_only}
    path=out/'manifest.json'
    if path.exists():
        current=json.loads(path.read_text())
        if current['config']!=cfg or current['tasks']!=ts:raise InfrastructureError('Refusing changed inputs, model, settings, dependencies or source on resume')
    else:
        if (out/'tasks').exists():raise InfrastructureError('Task output exists without manifest')
        current={'schema_version':1,'config':cfg,'task_count':len(ts),'created_at':now(),'tasks':ts,'coverage':coverage(ts,method),'requirements_metrics':'not_applicable','implementation':'author methods with documented project benchmark/runtime adaptations'}
        write_json(path,current)
        write_json(out/'experiment.json',{'dataset':dataset,'model':cfg['model'],'prompt':method,'sample_count':len(ts),'validation_only':validation_only,'created_at':now()})
        provenance=out/'provenance';provenance.mkdir()
        write_json(provenance/'source_sha256.json',cfg['source_sha256'])
        for name in cfg['source_sha256']:
            src=ROOT/name;dst=provenance/name;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(src.read_bytes())
    return current

def manifest(output,dataset,method,config,ts,validation_only=False):
    out=project_path(output);out.mkdir(parents=True,exist_ok=True)
    with lock(out,'generation'):
        return _manifest(out,dataset,method,config,ts,validation_only)

def worker_command(method):
    envname=METHODS[method]['env'];python=ROOT/'envs'/envname/'bin/python'
    prefix=['/lib64/ld-linux-x86-64.so.2'] if envname=='rescue' else []
    return prefix+[str(python),'-B','-m','table2_baselines.worker']

def worker_env(method):
    envname=METHODS[method]['env'];runtime=ROOT/'runtime/table2'/method
    for name in ['tmp','cache','hf','torch']:(runtime/name).mkdir(parents=True,exist_ok=True)
    env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2','MKL_NUM_THREADS':'2','TOKENIZERS_PARALLELISM':'false','TMPDIR':str(runtime/'tmp'),'TMP':str(runtime/'tmp'),'TEMP':str(runtime/'tmp'),'XDG_CACHE_HOME':str(runtime/'cache'),'HF_HOME':str(runtime/'hf'),'TORCH_HOME':str(runtime/'torch'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_DATASETS_OFFLINE':'1','TZ':'UTC','TZDIR':str(ROOT/'envs/codexity/lib/python3.10/site-packages/tzdata/zoneinfo'),'TIKTOKEN_CACHE_DIR':str(ROOT/'runtime/rescue/tiktoken'),'MPLCONFIGDIR':str(runtime/'cache/matplotlib')}
    return env

def run_one(output,m,t,fixture=None):
    method=m['config']['method'];d=output/'tasks'/f'{t["index"]:04d}';d.mkdir(parents=True,exist_ok=True)
    path=d/'generation.json';write_json(d/'task.json',t)
    if path.exists():
        old=json.loads(path.read_text())
        if old.get('key')!=t['key']:raise InfrastructureError('Task identity changed')
        if old['status']!='generation_error':
            if old.get('candidate') and sha((d/old['candidate']).read_bytes())!=old['candidate_sha256']:raise InfrastructureError('Saved candidate modified')
            return old
        history=d/'infrastructure_history';history.mkdir(exist_ok=True);write_json(history/f'{time.time_ns()}.json',old)
    result={'index':t['index'],'key':t['key'],'language':t['language'],'started_at':now(),'candidate':None,'requirements_status':'not_applicable'}
    if t['language'] not in METHODS[method]['languages']:
        result.update(status='unsupported_language',reason=METHODS[method]['note'])
    else:
        work=d/'method';work.mkdir(exist_ok=True)
        request=d/'worker_request.json';response=d/'worker_response.json'
        job={'method':method,'dataset':m['config']['dataset'],'config':m['config']['method_config'],'task':t,'output':str(work),'validation_only':m['config']['validation_only']}
        if fixture is not None:
            if not job['validation_only']:raise ValueError('Cannot use mock models in formal output')
            job['fixture_sha256']=sha(canonical(fixture));job['fixture']=fixture
        if request.exists() and json.loads(request.read_text())!=job:raise InfrastructureError('Worker request or fixture changed on resume')
        write_json(request,job);response.unlink(missing_ok=True)
        with (d/'worker.stdout').open('a') as stdout,(d/'worker.stderr').open('a') as stderr:
            try:
                proc=subprocess.run(worker_command(method)+[str(request),str(response)],env=worker_env(method),cwd=ROOT,stdout=stdout,stderr=stderr,timeout=7200)
                if not response.exists():raise InfrastructureError('Worker exited without result: '+str(proc.returncode))
                value=json.loads(response.read_text())
                if proc.returncode and value['status']!='generation_error':raise InfrastructureError('Worker exit/result conflict')
                result.update(status=value['status'],error=value.get('error'),model_call_count=value.get('model_call_count'),tool_call_count=value.get('tool_call_count'))
                (d/'raw_content.txt').write_text(value.get('raw_final_response',''))
                (d/'analysis.txt').write_text(json.dumps({k:v for k,v in value.items() if k not in ('candidate','raw_final_response')},ensure_ascii=False,indent=2)+'\n')
                (d/'completed_requirements.txt').write_text('')
                if value.get('candidate') is not None:
                    candidate=d/('candidate.'+t['language']);candidate.write_text(value['candidate']);result.update(candidate=candidate.name,candidate_sha256=sha(candidate.read_bytes()))
            except Exception as e:result.update(status='generation_error',error=repr(e))
    result['finished_at']=now();write_json(path,result);return result

def run(output,m,fixtures=None,auto_evaluate=False):
    output=project_path(output)
    with lock(output,'generation'):
        if json.loads((output/'manifest.json').read_text())!=m:raise InfrastructureError('Run manifest changed before generation lock')
        if m['config']['source_sha256']!=source_fingerprint():raise InfrastructureError('Source changed after manifest creation')
        for t in m['tasks']:
            result=run_one(output,m,t,None if fixtures is None else fixtures.get(t['key']))
            summarize(output)
            write_json(output/'status.json',{'phase':'generation','last_index':t['index'],'last_status':result['status'],'updated_at':now()})
            if result['status']=='generation_error':raise InfrastructureError('Generation infrastructure failure; checkpoints retained: '+str(output))
        write_json(output/'generation.done.json',{'time':now(),'task_count':m['task_count'],'coverage':m['coverage']});(output/'generation.done').touch()
    if auto_evaluate:
        from .evaluate import evaluate
        evaluate(output)
    return summarize(output)

def scores(rows,n):
    result={}
    for key in ['F','S','Joint']:
        vals=[(None if r.get('F') is None or r.get('S') is None else bool(r['F'] and r['S'])) if key=='Joint' else r.get(key) for r in rows]
        known=sum(v is not None for v in vals);passed=sum(v is True for v in vals)
        result[key+'-Pass@1']={'passed':passed,'evaluated':known,'total':n,'percent':100*passed/n if n and known==n else None}
    return result

def summarize(output):
    output=project_path(output);m=json.loads((output/'manifest.json').read_text());method=m['config']['method'];eligible=[t for t in m['tasks'] if t['language'] in METHODS[method]['languages']]
    gens=[];rows=[]
    for t in m['tasks']:
        d=output/'tasks'/f'{t["index"]:04d}'
        if (d/'generation.json').exists():gens.append(json.loads((d/'generation.json').read_text()))
        if t in eligible and (d/'evaluation.json').exists():rows.append(json.loads((d/'evaluation.json').read_text()))
    metrics=scores(rows,len(eligible));counts=dict(collections.Counter(g['status'] for g in gens))
    status='unsupported_dataset' if not eligible else 'generation_incomplete' if len(gens)<m['task_count'] or counts.get('generation_error') else 'complete' if all(x['evaluated']==len(eligible) for x in metrics.values()) else 'evaluation_incomplete'
    result={'schema_version':3,'experiment':{'dataset':m['config']['dataset'],'model':m['config']['model'],'prompt':method,'sample_count':m['task_count'],'validation_only':m['config']['validation_only']},'status':status,'coverage':m['coverage'],'generation':{'recorded':len(gens),'total':m['task_count'],'counts':counts},'evaluation':{'recorded':len(rows),'total':len(eligible)},'code_metrics':metrics,'metric_scope':'supported_languages_only','metric_unit':'percent','full_dataset_code_metrics':metrics if len(eligible)==m['task_count'] else None,'requirements':{'evaluation_status':'not_applicable','SR-Recall':None,'SR-Precision':None},'updated_at':now()}
    if m['config']['dataset']=='codesec_eval':result['subsets']={s:scores([r for r in rows if r['key'].startswith(s+'/')],sum(t.get('subset')==s for t in eligible)) for s in ['SecEvalBase','SecEvalPlus']}
    write_json(output/'result.json',result);write_json(output/'metrics.json',result);write_json(output/'per_task.json',rows)
    stream=io.StringIO();w=csv.writer(stream);w.writerow(['dataset','method','scope','eligible','unsupported','metric','passed','evaluated','percent'])
    for name,v in metrics.items():w.writerow([m['config']['dataset'],method,'supported_languages_only',len(eligible),m['coverage']['unsupported'],name,v['passed'],v['evaluated'],v['percent']])
    (output/'metrics.csv').write_text(stream.getvalue());return result
