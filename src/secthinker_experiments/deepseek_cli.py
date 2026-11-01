"""Prepare, run, resume or launch six experiments without changing model services."""
import argparse,json,os,shlex,socket,subprocess,sys,time,uuid
from pathlib import Path
from prompt_baselines.core import ROOT,tasks,now
from secthinker_baselines.cli import output_lock
from .artifacts import create_output,write_result,write_json

def prepare(model,endpoint,limit=0):
    if limit<0:raise ValueError('limit must be nonnegative')
    groups=[]
    for ds in ('codesec_eval','codeguard_plus'):
        n=min(limit,len(tasks(ds))) if limit else len(tasks(ds))
        for method in ('standard','cot','secthinker_style'):
            out=create_output(ds,model,method,n)
            groups.append({'dataset':ds,'method':method,'output':str(out),'limit':limit})
    parent=ROOT/'output/batches';parent.mkdir(parents=True,exist_ok=True)
    path=parent/('batch-'+uuid.uuid4().hex[:12]+'.json')
    write_json(path,{'schema_version':2,'created_at':now(),'model':model,'endpoint':endpoint,'max_tokens':8192,'concurrency':4,'seed':42,'groups':groups})
    return path

def environment(batch):
    rt=ROOT/'runtime/secthinker_experiments'/batch.stem
    for x in ('tmp','cache'): (rt/x).mkdir(parents=True,exist_ok=True)
    return {**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','TMPDIR':str(rt/'tmp'),'TMP':str(rt/'tmp'),'TEMP':str(rt/'tmp'),'XDG_CACHE_HOME':str(rt/'cache')}

def run(batch,phase,wait_for_generation=False,accept_runtime_update=False):
    batch=Path(batch).resolve()
    if not batch.is_relative_to(ROOT/'output/batches'):raise ValueError('Use a project batch manifest')
    cfg=json.loads(batch.read_text());env=environment(batch)
    rt=Path(env['TMPDIR']).parent;lockdir=rt/phase;lockdir.mkdir(exist_ok=True)
    status_path=rt/(phase+'.json');problems=[]
    with output_lock(lockdir):
        write_json(status_path,{'phase':'running','started_at':now(),'pid':os.getpid(),'hostname':socket.gethostname()})
        try:
            for group in cfg['groups']:
                out=Path(group['output']);ds=group['dataset'];method=group['method']
                if not out.resolve().is_relative_to(ROOT/'output'/ds):raise ValueError('Invalid batch output path')
                if phase=='generate':
                    cmd=[sys.executable,'-u','-B','-m','secthinker_baselines.cli','generate','--dataset',ds,'--method',method,'--output',str(out),'--endpoint',cfg['endpoint'],'--model',cfg['model'],'--concurrency',str(cfg['concurrency']),'--max-tokens',str(cfg['max_tokens']),'--seed',str(cfg['seed']),'--limit',str(group['limit'])]
                else:
                    while wait_for_generation and not (out/'generation.done').exists():
                        gp=rt/'generate.json'
                        state=json.loads(gp.read_text()) if gp.exists() else {}
                        gs=state.get('phase')
                        if gs=='running' and state.get('hostname')==socket.gethostname():
                            try:os.kill(state['pid'],0)
                            except ProcessLookupError:break
                        if gs in ('failed','complete','interrupted'):break
                        time.sleep(5)
                    if not (out/'generation.done').exists():
                        problems.append({'output':str(out),'error':'generation not complete'});continue
                    cmd=[sys.executable,'-u','-B','-m','secthinker_evaluation.runner',str(out)]
                    if accept_runtime_update:cmd.append('--accept-runtime-update')
                print(now(),phase,str(out),flush=True)
                with (out/(phase+'.log')).open('a') as log:
                    rc=subprocess.call(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                write_result(out)
                if rc:
                    problems.append({'output':str(out),'returncode':rc})
                    if phase=='generate':break # service failures must not fan out across more tasks
                elif phase=='generate':(out/'generation.done').touch()
            write_json(status_path,{'phase':'failed' if problems else 'complete','problems':problems,'updated_at':now()})
        except BaseException:
            write_json(status_path,{'phase':'interrupted','problems':problems,'updated_at':now()});raise
    return 1 if problems else 0

def launch(batch):
    batch=Path(batch).resolve()
    if not batch.is_relative_to(ROOT/'output/batches') or not batch.is_file():raise ValueError('Use an existing project batch manifest')
    env=environment(batch);rt=Path(env['TMPDIR']).parent
    socket=ROOT/'runtime'/('st-'+batch.stem+'.sock');name='secthinker-'+batch.stem
    base=[str(ROOT/'bin/tmux'),'-S',str(socket)]
    def call(*args):subprocess.run(base+list(args),env=env,check=True)
    exists=subprocess.run(base+['has-session','-t',name],env=env,capture_output=True).returncode==0
    if not exists:
        call('-f','/dev/null','new-session','-d','-s',name,'-n','generation','-c',str(ROOT),'sleep 60')
        call('set-option','-t',name,'remain-on-exit','on')
    for win,phase in [('generation','generate'),('evaluation','evaluate')]:
        command=[sys.executable,'-u','-B','-m','secthinker_experiments.deepseek_cli','run','--batch',str(batch),'--phase',phase]
        if phase=='evaluate':command.append('--wait-for-generation')
        shell=shlex.join(command)+' >> '+shlex.quote(str(rt/(win+'.log')))+' 2>&1'
        names=subprocess.check_output(base+['list-windows','-t',name,'-F','#{window_name}'],env=env,text=True).splitlines()
        target=name+':'+win
        restart = win not in names or (not exists and win=='generation')
        if not restart:
            restart=subprocess.check_output(base+['display-message','-p','-t',target,'#{pane_dead}'],env=env,text=True).strip()=='1'
        if restart:
            # Clear a previous terminal status before the evaluator can observe it.
            write_json(rt/(phase+'.json'),{'phase':'pending','updated_at':now()})
            if win not in names:call('new-window','-d','-t',name,'-n',win,'-c',str(ROOT),shell)
            elif not exists and win=='generation':call('respawn-pane','-k','-t',target,shell)
            else:call('respawn-pane','-t',target,shell)
    print(json.dumps({'session':name,'socket':str(socket),'batch':str(batch)},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--model',required=True);a.add_argument('--endpoint',required=True);a.add_argument('--limit',type=int,default=0)
    a=sub.add_parser('run');a.add_argument('--batch',type=Path,required=True);a.add_argument('--phase',choices=['generate','evaluate'],required=True);a.add_argument('--wait-for-generation',action='store_true');a.add_argument('--accept-runtime-update',action='store_true')
    a=sub.add_parser('launch');a.add_argument('--batch',type=Path,required=True)
    a=sub.add_parser('summarize');a.add_argument('output',type=Path)
    args=p.parse_args()
    if args.action=='prepare':print(prepare(args.model,args.endpoint,args.limit))
    elif args.action=='run':sys.exit(run(args.batch,args.phase,args.wait_for_generation,args.accept_runtime_update))
    elif args.action=='launch':launch(args.batch)
    else:print(json.dumps(write_result(args.output),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
