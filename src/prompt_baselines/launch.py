import os,sys,json,shlex,subprocess,datetime
from pathlib import Path
R=Path(__file__).resolve().parents[2];node=sys.argv[1]
base=R/'runs/2026-10-21_qwen_prompt_baselines';base.mkdir(parents=True,exist_ok=True)
rt=R/'runtime/prompt_baselines'/node;rt.mkdir(parents=True,exist_ok=True)
for d in ['tmp','cache','tmux']:(rt/d).mkdir(exist_ok=True)
env={**os.environ,'TMPDIR':str(rt/'tmp'),'XDG_CACHE_HOME':str(rt/'cache'),'PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(R/'src'),'TMUX_TMPDIR':str(rt/'tmux')}
tmux=R/'bin/tmux';socket=rt/'tmux/server.sock'
entries=[('gpu03','direct_prompt',18088),('gpu47','self_generated_hints',18098)]
dataset='codesec_eval' if node=='a' else 'codeguard_plus'
for group,method,port in entries:
 name=f'r1-{method}-{dataset}';out=base/f'{node}_{group}_{method}_{dataset}';out.mkdir(exist_ok=True)
 cmd=['/usr/bin/python3','-u','-B','-m','prompt_baselines.core','generate','--dataset',dataset,'--method',method,'--endpoint',f'http://127.0.0.1:{port}/v1','--node',node,'--group',group,'--output',str(out)]
 marker=R/'runs/_setup/prompt_baselines'/f'{dataset}.ready'
 shell='set -eu\n'+''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in env.items() if k in ['TMPDIR','XDG_CACHE_HOME','PYTHONDONTWRITEBYTECODE','PYTHONPATH','TMUX_TMPDIR'])+'cd '+shlex.quote(str(R))+'\n'+shlex.join(cmd)+'\necho "Generation complete; waiting for validated evaluator."\nwhile [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 30; done\n'+shlex.join(['/usr/bin/python3','-u','-B','-m','prompt_baselines.core','evaluate','--output',str(out)])+'\n'
 script=out/'run.sh';script.write_text(shell)
 log=out/'run.log';wrapped=f'/bin/bash {shlex.quote(str(script))} >> {shlex.quote(str(log))} 2>&1'
 status=subprocess.run([str(tmux),'-S',str(socket),'has-session','-t',name],env=env,capture_output=True)
 if status.returncode:
  subprocess.run([str(tmux),'-S',str(socket),'-f','/dev/null','new-session','-d','-s',name,'-c',str(R),wrapped],env=env,check=True)
  subprocess.run([str(tmux),'-S',str(socket),'set-option','-t',name,'remain-on-exit','on'],env=env,check=True)
 else:
  dead=subprocess.check_output([str(tmux),'-S',str(socket),'display-message','-p','-t',name+':0','#{pane_dead}'],env=env,text=True).strip()
  if dead=='1':subprocess.run([str(tmux),'-S',str(socket),'respawn-pane','-t',name+':0',wrapped],env=env,check=True)
 print(json.dumps({'node':node,'session':name,'socket':str(socket),'output':str(out),'gpu_group':group},ensure_ascii=False),flush=True)
