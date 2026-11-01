"""Build a traceable compatibility copy; official checkout remains unchanged."""
import ast,hashlib,json
from pathlib import Path
R=Path(__file__).resolve().parents[2]; S=R/'baseline/AutoSafeCoder'; D=R/'src/autosafecoder_prepared'
manifest=json.loads((R/'downloads/AutoSafeCoder/source-verification.json').read_text())
for f in manifest['files']:
    assert hashlib.sha256((S/f['path']).read_bytes()).hexdigest()==f['sha256'],f['path']
previous=R/'downloads/AutoSafeCoder/compatibility-changes.json'
if previous.exists():
    for f in json.loads(previous.read_text())['files']:
        assert hashlib.sha256((D/f['path']).read_bytes()).hexdigest()==f['prepared_sha256'],'Refusing to overwrite changed prepared file: '+f['path']
def replace_once(text,old,new):
    assert text.count(old)==1,(old,text.count(old))
    return text.replace(old,new)
changes=[]
for p in sorted(S.glob('*.py')):
    source=p.read_text();text=source
    if p.name=='utils.py':
        text=replace_once(text,'openai.api_base = "https://api.aiohub.org/v1"','')
        text=replace_once(text,"openai.api_key = 'YOUR-API-KEY-HERE'",'')
        text=replace_once(text,'model="gpt-4o"','model=None\n_completion_client=None\n\ndef configure_client(client, model_name):\n    if client is None or not isinstance(model_name,str) or not model_name.strip():\n        raise ValueError("An explicit client and model are required")\n    global model, _completion_client\n    model=model_name\n    _completion_client=client\n\ndef request_completion(**kwargs):\n    if _completion_client is None or model is None:\n        raise RuntimeError("No generation model/client configured")\n    kwargs["model"]=model\n    return _completion_client.chat.completions.create(**kwargs)\n')
        text=text.replace('openai.chat.completions.create(','request_completion(')
        text=text.replace('"./prompts_fewshot/','"'+str(S/'prompts_fewshot')+'/')
    elif p.name=='main.py':
        text=replace_once(text,'    def __init__(self, entry):\n','    def __init__(self, entry):\n        self.entry = entry\n')
        text=text.replace("entry['ID']","self.entry['ID']")
        text=replace_once(text,'InputMutatorAgent(inputs, self.code,functionname)','InputMutatorAgent(inputs, functionname,self.code)')
        text=replace_once(text,'result,passed,_inputs,_functionname = execute_fuzz(self.code,self.test_inputs, 3)',"result,passed,_inputs,_functionname = execute_fuzz(self.code,inputs['inputs'], 3)")
        text=replace_once(text,"new_failed_inputs.append({'inputs': inputs, 'result': result})","new_failed_inputs.append({'inputs': inputs['inputs'], 'result': result})")
        text=replace_once(text,'                        fuzzing_test_status = "error running function"\n                        break','                        raise RuntimeError("Fuzz repair replay failed") from e')
        text=replace_once(text,'if __name__ == "__main__":','if __name__ == "__main__":\n    raise SystemExit("Preparation only: use bin/autosafecoder.sh inspect|validate; formal benchmark entry is not enabled")')
    elif p.name=='executor_agent_safe.py':
        text=replace_once(text,'completion_id: Optional[int] = None) -> Dict:','completion_id: Optional[int] = None, *, trusted_fixture_only=False) -> Dict:')
        text=replace_once(text,'    def get_exec_code(code, inputs_json):','    if not trusted_fixture_only:\n        raise RuntimeError("A sandbox backend must be injected before generated-code execution. Validation allows trusted fixtures only.")\n\n    def get_exec_code(code, inputs_json):')
        text=replace_once(text,'exec_globals = {}','exec_globals = {"__name__": "__main__"}')
        text=replace_once(text,'print(json.dumps({{"status": "error", "error": str(e)}}))','raise')
        text=replace_once(text,"    return result[0], result[0] == 'passed', inputs_list[0], func_names[0]","    try:\n        answer=(result[0], result[0] == 'passed', inputs_list[0] if inputs_list else input_json, func_names[0] if func_names else None)\n    finally:\n        manager.shutdown()\n    return answer")
    elif p.name=='executor_static.py':
        start=text.index('    def execute_static_analysis(self,code):')
        end=text.index('    def execute_static_analysis_gpt(self,code):',start)
        text=text[:start]+'''    def execute_static_analysis(self,code):
        # Bandit analyzes Python syntax; process/report errors are never SAFE.
        import sys
        path=None
        try:
            with tempfile.NamedTemporaryFile(delete=False,suffix='.py') as f:
                f.write(code.encode('utf-8'));path=f.name
            result=subprocess.run([sys.executable,'-m','bandit','-r',path,'-f','json'],capture_output=True,text=True,timeout=6)
            if result.returncode not in (0,1):
                return FResult.FAILURE,'analysis_error',result.stderr
            report=json.loads(result.stdout)
            if report.get('errors'):
                return FResult.FAILURE,'analysis_error',json.dumps(report['errors'])
            findings=report.get('results')
            if not isinstance(findings,list):
                return FResult.FAILURE,'invalid_report','Missing Bandit results'
            if findings:
                first=findings[0]
                return FResult.ERROR,'CWE-'+str(first.get('issue_cwe',{}).get('id','unknown')),first.get('issue_text','')
            if result.returncode!=0:
                return FResult.FAILURE,'analysis_error','Bandit failed without findings'
            return FResult.SAFE,'0',''
        except subprocess.TimeoutExpired:
            return FResult.TIMED_OUT,'timeout','Bandit timeout'
        except (OSError,ValueError,TypeError) as e:
            return FResult.FAILURE,'analysis_error',str(e)
        finally:
            if path and os.path.exists(path):os.remove(path)

'''+text[end:]
    elif p.name=='eval_bandit.py':
        continue
    ast.parse(text,filename=str(D/p.name))
    (D/p.name).write_text(text)
    changes.append({'path':p.name,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'prepared_sha256':hashlib.sha256(text.encode()).hexdigest(),'changed':text!=source})
record={'source_commit':manifest['commit'],'files':changes,'fixes':['Explicit client/model injection; remove default endpoint/model/key assignments','Resolve original few-shot prompts by absolute path','Use self.entry rather than ambient global entry','Pass mutator function name/code in correct order','Replay each actual failing input; preserve flat failure records; do not mark replay errors fixed','Invoke __main__ in executor and propagate target exceptions; close IPC manager; handle missing child records','Disable generated-code host execution; require future sandbox backend; trusted fixtures only for validation','Normalize Bandit result/error handling; use python -m bandit','Disable direct prepared-main benchmark launch']}
previous.write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'files':len(changes),'modified':sum(f['changed'] for f in changes)}))
