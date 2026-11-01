from pathlib import Path
import subprocess,sys,shlex
R=Path(__file__).resolve().parents[2];node=sys.argv[1];socket=R/'runtime/prompt_baselines'/node/'tmux/server.sock';tmux=R/'bin/tmux'
for out in (R/'runs/2026-10-21_qwen_prompt_baselines').glob(node+'_*'):
 manifest=out/'manifest.json'
 if not manifest.exists():continue
 import json
 cfg=json.loads(manifest.read_text())['config'];session='r1-'+cfg['method']+'-'+cfg['dataset']
 names=subprocess.check_output([str(tmux),'-S',str(socket),'list-windows','-t',session,'-F','#{window_name}'],text=True).splitlines()
 if 'logs' not in names:subprocess.run([str(tmux),'-S',str(socket),'new-window','-t',session,'-n','logs','-c',str(R),shlex.join(['/usr/bin/tail','-n','35','-F',str(out/'run.log')])],check=True)
 subprocess.run([str(tmux),'-S',str(socket),'select-window','-t',session+':logs'],check=True)
 print(session,flush=True)
