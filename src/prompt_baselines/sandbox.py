import contextlib,hashlib,json,os,shutil,signal,subprocess,time,uuid
from pathlib import Path
from .core import ROOT,save
ROOTFS=ROOT/'envs/benchmark-rootfs'
@contextlib.contextmanager
def disk_lock(path):
 while True:
  try:path.mkdir();break
  except FileExistsError:time.sleep(.2)
 try:yield
 finally:path.rmdir()
def run_sandbox(files,command,output,timeout=15,collect=(),allow_icmp=False,allow_server=False):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 lock=ROOT/'runtime/prompt_baselines/evaluation.lockdir';lock.parent.mkdir(parents=True,exist_ok=True)
 with disk_lock(lock):
  for folder in ['tmp','var/tmp','work']:
   parent=ROOTFS/folder
   for p in parent.iterdir():
    if p.is_dir() and not p.is_symlink():shutil.rmtree(p)
    else:p.unlink()
  job=uuid.uuid4().hex;work=ROOTFS/'work'/job;work.mkdir(mode=0o777);os.chmod(work,0o777)
  for name,data in files.items():
   p=work/name;p.parent.mkdir(parents=True,exist_ok=True)
   if isinstance(data,Path):shutil.copyfile(data,p)
   else:p.write_bytes(data.encode() if isinstance(data,str) else data)
   os.chmod(p,0o666 if name.endswith('stat.json') else 0o644)
  for p in work.rglob('*'):
   if p.is_dir():os.chmod(p,0o777)
  uid=300000+int(job[:6],16)%1000000
  (ROOTFS/'etc/passwd').write_text(f'root:x:0:0:root:/root:/bin/sh\nevaluator:x:{uid}:{uid}:evaluator:/root:/bin/sh\n')
  argv=['/usr/bin/python3','-B',str(Path(__file__).with_name('sandbox_exec.py')),str(ROOTFS),'/work/'+job,str(uid),('server' if allow_server else str(int(allow_icmp))),*command]
  started=time.monotonic()
  with open(output/'stdout.txt','w') as out,open(output/'stderr.txt','w') as err:
   proc=subprocess.Popen(argv,stdout=out,stderr=err,start_new_session=True,cwd=ROOT,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
   timed_out=False
   try:proc.wait(timeout=timeout)
   except subprocess.TimeoutExpired:
    timed_out=True;os.killpg(proc.pid,signal.SIGKILL);proc.wait()
   finally:
    try:os.killpg(proc.pid,signal.SIGKILL)
    except ProcessLookupError:pass
  result={'returncode':proc.returncode,'timeout':timed_out,'elapsed_s':time.monotonic()-started,'uid':uid,'isolation':'chroot+uid+seccomp+rlimits','collected':{}}
  for name in collect:
   p=work/name
   if p.is_file() and not p.is_symlink() and p.stat().st_size<4*1024**2:
    result['collected'][name]=p.read_text(errors='replace')
  save(output/'execution.json',result)
  return result
CSE_RUNNER=r"""import json,traceback
p=json.load(open('payload.json'))
result={'passed':False}
try:
 ns={'__name__':'codesec_eval_candidate','__file__':'candidate.py'}
 exec(compile(open('candidate.py').read(),'candidate.py','exec'),ns)
 candidate=ns[p['entry']]
 exec(compile(p['test'],'benchmark_test.py','exec'),ns)
 ns['check'](candidate)
 result['passed']=True
except BaseException as e:result.update(error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc())
with open('result.json','w') as f:json.dump(result,f)
"""
def codesec_test(code,entry,test,output):
 result=run_sandbox({'candidate.py':code,'payload.json':json.dumps({'entry':entry,'test':test}),'runner.py':CSE_RUNNER},['/usr/bin/python3','-B','runner.py'],output,timeout=10,collect=['result.json'],allow_icmp=(entry=='ping_host'))
 report=result['collected'].get('result.json')
 if report:
  try:return {**json.loads(report),'execution':result}
  except Exception:pass
 return {'passed':False,'error_type':'Timeout' if result['timeout'] else 'ProcessError','execution':result}

def audit_runtime():
 manifest=json.loads((ROOT/'runs/_setup/prompt_baselines/rootfs_static_manifest.json').read_text())
 changed=[]
 for name,expected in manifest.items():
  p=ROOTFS/name
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:changed.append(name)
 if changed:raise RuntimeError('Sandbox runtime integrity check failed: '+str(changed[:10]))
 return {'files_verified':len(manifest),'changed':[]}
