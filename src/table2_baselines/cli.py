import argparse,json,runpy
from pathlib import Path
from .registry import ROOT,METHODS,DATASETS
from .common import selected_tasks,coverage,configuration,write_json,project_path
from .runner import new_output,manifest,run,summarize,source_fingerprint

def prepare():
    out=ROOT/'runs/_setup/table2_2026-10-31/plans';out.mkdir(parents=True,exist_ok=True);matrix=[]
    for method in METHODS:
        for dataset in DATASETS:
            ts=selected_tasks(dataset,method);cover=coverage(ts,method)
            plan={'method':method,'dataset':dataset,'coverage':cover,'tasks':[{'task':t,'status':'eligible' if t['language'] in METHODS[method]['languages'] else 'unsupported_language'} for t in ts],'generation_model':None,'formal_experiments_started':False,'note':METHODS[method]['note']}
            write_json(out/(method+'.'+dataset+'.json'),plan)
            matrix.append({k:v for k,v in plan.items() if k!='tasks'})
    write_json(out/'coverage.json',matrix);print(json.dumps({'public_tasks_per_method':358,'method_variants':len(METHODS),'output':str(out),'coverage':matrix},ensure_ascii=False,indent=2));return matrix

def main():
    p=argparse.ArgumentParser(description='Table 2 integration; all models unconfigured until explicitly selected')
    p.add_argument('command',choices=['inspect','prepare','validate','generate','evaluate','summarize'])
    p.add_argument('--method',choices=METHODS);p.add_argument('--dataset',choices=DATASETS)
    p.add_argument('--config',type=Path,default=ROOT/'config/table2/runtime.json')
    p.add_argument('--output',type=Path);p.add_argument('--auto-evaluate',action='store_true')
    a=p.parse_args()
    if a.command=='prepare':prepare();return
    if a.command=='inspect':
        cfg=json.loads(project_path(a.config).read_text())
        print(json.dumps({'formal_experiments_enabled':cfg['formal_experiments_enabled'],'methods':METHODS,'model_roles_configured':{k:{role:bool(v.get('model') and v.get('base_url')) for role,v in m['models'].items()} for k,m in cfg['methods'].items()}},default=str,indent=2));return
    if a.command=='validate':runpy.run_path(str(ROOT/'services/table2/validate.py'),run_name='__main__');return
    if a.command=='generate':
        if not a.method or not a.dataset:p.error('generate requires --method and --dataset')
        _,cfg=configuration(a.config,a.method,live=True);ts=selected_tasks(a.dataset,a.method)
        out=project_path(a.output) if a.output else new_output(a.dataset,a.method,cfg['models']['generation']['model'],len(ts))
        m=manifest(out,a.dataset,a.method,cfg,ts);print('Output: '+str(out),flush=True);run(out,m,auto_evaluate=a.auto_evaluate)
    else:
        if not a.output:p.error('output required')
        if a.command=='evaluate':
            from .evaluate import evaluate
            print(json.dumps(evaluate(a.output),indent=2))
        else:print(json.dumps(summarize(a.output),indent=2))
if __name__=='__main__':main()
