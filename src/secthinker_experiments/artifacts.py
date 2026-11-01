import collections, datetime, hashlib, json, os, re, uuid
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from prompt_baselines.core import ROOT, now

def write_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('w') as f:
            json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        tmp.replace(path)
    finally:tmp.unlink(missing_ok=True)

def slug(value):
    name=re.sub(r'[^A-Za-z0-9_.-]+','-',value).strip('.-')
    if not name:raise ValueError('Empty model/path name')
    return name

def create_output(dataset,model,prompt,n):
    if dataset not in ('codesec_eval','codeguard_plus') or n<1:raise ValueError('Invalid dataset/sample count')
    parent=ROOT/'output'/dataset;parent.mkdir(parents=True,exist_ok=True)
    try:
        timestamp_zone=ZoneInfo('Asia/Shanghai')
    except ZoneInfoNotFoundError:
        # Current experiment timestamps use Beijing time (UTC+08:00), even
        # in minimal containers that have no system/package tzdata installed.
        timestamp_zone=datetime.timezone(datetime.timedelta(hours=8))
    stamp=datetime.datetime.now(timestamp_zone).strftime('%Y%m%dT%H%M%S%f')
    out=parent/f'{slug(model)}_{slug(prompt)}_n{n}_{stamp}'
    out.mkdir() # exclusive; timestamps never determine resume identity
    write_json(out/'experiment.json',{'dataset':dataset,'model':model,'prompt':prompt,'sample_count':n,'created_at':now(),'timestamp_timezone':'Asia/Shanghai'})
    write_result(out)
    return out

def scores(rows,n):
    checks={'F-Pass@1':lambda r:r.get('F'),'S-Pass@1':lambda r:r.get('S'),
            'Joint-Pass@1':lambda r:None if r.get('F') is None or r.get('S') is None else bool(r['F'] and r['S'])}
    result={}
    for name,fn in checks.items():
        values=[fn(r) for r in rows];known=sum(v is not None for v in values);passed=sum(v is True for v in values)
        result[name]={'passed':passed,'evaluated':known,'total':n,'percent':100*passed/n if n and known==n else None}
    return result

def write_result(output):
    output=Path(output)
    m=json.loads((output/'manifest.json').read_text()) if (output/'manifest.json').exists() else None
    meta=json.loads((output/'experiment.json').read_text()) if (output/'experiment.json').exists() else {}
    if m:
        cfg=m['config'];meta.update(dataset=cfg['dataset'],model=cfg['model'],prompt=cfg['method'],sample_count=m['task_count'],created_at=m['created_at'])
    n=meta['sample_count'];gens=[];rows=[];req=0;failures=[]
    for i in range(n):
        d=output/'tasks'/f'{i:04d}'
        if (d/'generation.json').exists():
            g=json.loads((d/'generation.json').read_text());gens.append(g)
        if (d/'completed_requirements.txt').exists() and (d/'completed_requirements.txt').read_text().strip():req+=1
        if (d/'evaluation.json').exists():
            r=json.loads((d/'evaluation.json').read_text());rows.append(r)
            if r.get('F') is None or r.get('S') is None:failures.append({'index':i,'key':r.get('key'),'path':str(d/'evaluation.json')})
    metric=scores(rows,n);complete=all(v['evaluated']==n for v in metric.values())
    gc=dict(collections.Counter(g['status'] for g in gens))
    status='complete' if complete else 'generation_incomplete' if len(gens)<n or gc.get('generation_error',0) else 'evaluation_incomplete'
    result={'schema_version':2,'experiment':meta,'status':status,'updated_at':now(),
        'generation':{'recorded':len(gens),'total':n,'counts':gc},
        'evaluation':{'recorded':len(rows),'total':n,'infrastructure_or_unknown_tasks':failures},
        'code_metrics':metric,'metric_unit':'percent','joint_definition':'Functional AND security checks both pass for the same single candidate',
        'requirements':{'saved_samples':req,'evaluation_status':'pending_manual_evaluation','ground_truth_available':False,'SR-Recall':None,'SR-Precision':None},
        'artifacts':{'samples':'tasks/{sample_index:04d}/','requirements':'completed_requirements.txt','analysis':'analysis.txt','raw_output':'raw_content.txt','code':'candidate.{py,c,cpp}','evaluation':'evaluation.json'}}
    if meta['dataset']=='codesec_eval':
        from prompt_baselines.core import tasks
        selected=tasks('codesec_eval')[:n]
        result['subsets']={s:scores([r for r in rows if r.get('key','').startswith(s+'/')],sum(t['subset']==s for t in selected)) for s in ('SecEvalBase','SecEvalPlus') if any(t['subset']==s for t in selected)}
    write_json(output/'result.json',result);return result
