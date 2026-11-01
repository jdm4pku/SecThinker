"""All dynamic method execution uses the existing locked chroot/UID/seccomp jail."""
import ast,json
from pathlib import Path
from .jail import run_sandbox
from .common import project_path,InfrastructureError,write_json,sha

def _run_python(code,output,timeout=3,inputs=None,entry=None):
    out=project_path(output)
    if timeout<=0 or timeout>120:raise ValueError('Invalid sandbox time budget')
    if inputs is not None and not isinstance(inputs,dict):
        return {'status':'invalid_inputs','passed':False,'error':'Fuzz inputs must be a JSON object','stdout':''}
    payload={'code':code,'inputs':inputs,'entry':entry}
    runner="""import ast,contextlib,io,json,traceback
p=json.load(open('payload.json'));result={'passed':False};stream=io.StringIO()
try:
 ns={'__name__':'__main__','__file__':'candidate.py'}
 with contextlib.redirect_stdout(stream),contextlib.redirect_stderr(stream):
  exec(compile(p['code'],'candidate.py','exec'),ns)
  if p['inputs'] is not None:
   entry=p['entry']
   if not entry:
    names=[n.name for n in ast.parse(p['code']).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    if not names:raise ValueError('No function defined')
    entry=names[0]
   value=ns[entry](**p['inputs'])
   json.dumps(value)  # Preserve the author's JSON-serializable-result contract.
 result['passed']=True
except BaseException as e:result.update(error_type=type(e).__name__,error=str(e),traceback=traceback.format_exc())
result['stdout']=stream.getvalue()[-65536:]
with open('result.json','w') as f:json.dump(result,f)
"""
    result=run_sandbox({'runner.py':runner,'payload.json':json.dumps(payload)},['/usr/bin/python3','-B','runner.py'],out,timeout=timeout,collect=['result.json'])
    if result['timeout']:report={'passed':False,'status':'timeout','stdout':'','error':'Execution timed out'}
    elif 'result.json' in result['collected']:
        try:report=json.loads(result['collected']['result.json'])
        except ValueError as e:raise InfrastructureError('Invalid sandbox result') from e
        if not isinstance(report.get('passed'),bool):raise InfrastructureError('Missing sandbox result status')
        report['status']='passed' if report['passed'] else 'runtime_error'
    else:
        stderr=(out/'stderr.txt').read_text(errors='replace')
        if 'sandbox_exec.py' in stderr or 'Operation not permitted' in stderr and result['returncode']==1:
            raise InfrastructureError('Sandbox launcher failed: '+stderr[-2000:])
        report={'passed':False,'status':'process_error','stdout':'','error':'Candidate process exited without report'}
    report.update(execution=result,code_sha256=sha(code));write_json(out/'result.normalized.json',report)
    return report


def run_python(code,output,timeout=3,inputs=None,entry=None):
    import os,subprocess,sys
    out=project_path(output);out.mkdir(parents=True,exist_ok=True)
    request=out/'sandbox_request.json';response=out/'sandbox_response.json'
    write_json(request,dict(code=code,output=str(out/'jail'),timeout=timeout,inputs=inputs,entry=entry))
    root=Path(__file__).resolve().parents[2]
    env={'PATH':'/usr/bin:/bin','PYTHONPATH':str(root/'src'),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(root/'runtime/table2/tmp'),'LANG':'C.UTF-8'}
    try:
        proc=subprocess.run(['/usr/bin/python3.10','-B','-m','table2_baselines.sandbox',str(request),str(response)],env=env,cwd=root,capture_output=True,text=True,timeout=timeout+180)
    except subprocess.TimeoutExpired as e:raise InfrastructureError('Sandbox controller unavailable or busy beyond deadline') from e
    (out/'controller.stdout').write_text(proc.stdout);(out/'controller.stderr').write_text(proc.stderr)
    if proc.returncode or not response.exists():raise InfrastructureError('Sandbox controller failed: '+proc.stderr[-1500:])
    return json.loads(response.read_text())

if __name__=='__main__':
    import sys
    req=json.loads(project_path(sys.argv[1]).read_text())
    result=_run_python(**req)
    write_json(project_path(sys.argv[2]),result)
