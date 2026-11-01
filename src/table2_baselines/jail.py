"""Disposable full-copy jails: no writable inode is shared with benchmark runtime."""
import concurrent.futures,contextlib,hashlib,json,os,shutil,signal,subprocess,sys,time,uuid
from pathlib import Path
from .common import ROOT,write_json,InfrastructureError
save=write_json
BASE=ROOT/'envs/benchmark-rootfs'

def remove_root(root):
    parent=(ROOT/'runtime/table2/jails').resolve()
    root=Path(root)
    if root.parent.resolve()!=parent or root.is_symlink():raise ValueError('Unexpected private jail cleanup path')
    # Files are owned exclusively by this invocation. No shared tree is traversed.
    files=[];directories=[]
    for folder,dirs,names in os.walk(root,followlinks=False):
        directories.append(Path(folder))
        files.extend(Path(folder)/n for n in names)
        files.extend(Path(folder)/n for n in dirs if (Path(folder)/n).is_symlink())
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        list(pool.map(lambda q:q.unlink(missing_ok=True),files))
    for q in sorted(directories,key=lambda q:len(q.parts),reverse=True):q.rmdir()

def clone_root():
    started=time.monotonic();parent=ROOT/'runtime/table2/jails';parent.mkdir(parents=True,exist_ok=True)
    root=parent/uuid.uuid4().hex;root.mkdir(mode=0o755)
    index=json.loads((ROOT/'tools/table2/rootfs-index.json').read_text())
    original=ROOT/'runs/_setup/prompt_baselines/rootfs_static_manifest.json'
    if hashlib.sha256(original.read_bytes()).hexdigest()!=index['source_manifest_sha256']:
        remove_root(root);raise InfrastructureError('Runtime source manifest changed; rebuild the private image')
    fd=None
    try:
        for rel in index['directories']:
            name=Path(rel)
            if name.is_absolute() or '..' in name.parts:raise ValueError('Unsafe indexed directory')
            (root/name).mkdir(parents=True,exist_ok=True,mode=0o755)
        for name in ['work','tmp','var/tmp']:(root/name).mkdir(parents=True,exist_ok=True,mode=0o777)
        fd=os.open(ROOT/'tools/table2/rootfs.blob',os.O_RDONLY)
        if os.fstat(fd).st_size!=index['blob_bytes']:raise InfrastructureError('Runtime image size changed')
        def copy(pair):
            rel,entry=pair;name=Path(rel)
            if name.is_absolute() or '..' in name.parts:raise ValueError('Unsafe indexed file')
            raw=os.pread(fd,entry['size'],entry['offset'])
            if len(raw)!=entry['size'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise InfrastructureError('Runtime image data changed: '+rel)
            target=root/name
            out=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,entry['mode'])
            with os.fdopen(out,'wb') as stream:stream.write(raw)
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:list(pool.map(copy,index['files'].items()))
        # All regular data is materialized before symlinks, preventing host-side traversal.
        for rel,target in index['symlinks'].items():
            name=Path(rel)
            if name.is_absolute() or '..' in name.parts:raise ValueError('Unsafe indexed symlink')
            (root/name).symlink_to(target)
        return root,{'files_verified':len(index['files']),'copy_seconds':time.monotonic()-started,'shared_writable_inodes':False,'source_manifest_sha256':index['source_manifest_sha256']}
    except BaseException:
        remove_root(root);raise
    finally:
        if fd is not None:os.close(fd)

def run_sandbox(files,command,output,timeout=15,collect=(),allow_icmp=False,allow_server=False):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    root,provenance=clone_root();start=time.monotonic()
    try:
        work=root/'work/job';work.mkdir(mode=0o777)
        for name,data in files.items():
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe sandbox input path')
            p=work/relative;p.parent.mkdir(parents=True,exist_ok=True,mode=0o777)
            raw=data.read_bytes() if isinstance(data,Path) else data.encode() if isinstance(data,str) else data
            fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o666 if name.endswith('stat.json') else 0o644)
            with os.fdopen(fd,'wb') as stream:stream.write(raw)
        uid=300000+int(root.name[:6],16)%1000000
        (root/'etc/passwd').write_text(f'root:x:0:0:root:/root:/bin/sh\nevaluator:x:{uid}:{uid}:evaluator:/root:/bin/sh\n')
        argv=['/usr/bin/python3.10','-B',str(Path(__file__).with_name('sandbox_exec.py')),str(root),'/work/job',str(uid),'server' if allow_server else str(int(allow_icmp)),*command]
        with (output/'stdout.txt').open('w') as stdout,(output/'stderr.txt').open('w') as stderr:
            process=subprocess.Popen(argv,cwd=ROOT,stdout=stdout,stderr=stderr,start_new_session=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            timed_out=False
            try:process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out=True;os.killpg(process.pid,signal.SIGKILL);process.wait()
            finally:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
        # Launcher failures must never be scored as ordinary candidate failures.
        stderr=(output/'stderr.txt').read_text(errors='replace')
        if 'sandbox_exec.py' in stderr and 'Traceback' in stderr:raise InfrastructureError('Sandbox launcher failed: '+stderr[-2000:])
        result={'returncode':process.returncode,'timeout':timed_out,'elapsed_s':time.monotonic()-start,'uid':uid,'isolation':'disposable-private-rootfs+chroot+uid+seccomp+rlimits','runtime_clone':provenance,'collected':{}}
        for name in collect:
            relative=Path(name)
            if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe collected path')
            p=work/relative
            if p.resolve().is_relative_to(root.resolve()) and p.is_file() and not p.is_symlink() and p.stat().st_size<4*1024**2:result['collected'][name]=p.read_text(errors='replace')
        save(output/'execution.json',result);return result
    finally:
        remove_root(root)
        save(output/'jail_cleanup.json',{'removed':not root.exists(),'runtime_source':str(BASE),'private_root':str(root)})

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
  p=BASE/name
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:changed.append(name)
 if changed:raise RuntimeError('Sandbox runtime integrity check failed: '+str(changed[:10]))
 return {'files_verified':len(manifest),'changed':[]}
