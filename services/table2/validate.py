"""No formal generation: synthetic model responses, real tools/sandbox, exact protocol checks."""
import ast,copy,hashlib,io,json,os,subprocess,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from table2_baselines.registry import ROOT,METHODS
from table2_baselines.common import public_task,candidate,coverage,selected_tasks,configuration,sha,write_json,InvalidOutput,InfrastructureError
from table2_baselines.runner import manifest,run,run_one,summarize,source_fingerprint
from table2_baselines.transport import Transport
from table2_baselines.sandbox import run_python
from table2_baselines import evaluate as ev
from secthinker_evaluation import codeguard as cg
from secthinker_evaluation.sandbox import audit_runtime
SETUP=ROOT/'runs/_setup/table2_2026-10-31'
WORK=Path(tempfile.mkdtemp(prefix='validation-',dir=SETUP))
CONFIG=json.loads((ROOT/'config/table2/runtime.json').read_text())
DETAILS={'worker_cases':[]}

def task(language='py',prefix=False,index=0):
    t={'key':'fixture/'+str(index)+'-'+language,'index':index,'language':language}
    if prefix:
        t['prefix']=('# fixed prefix: add two integers\ndef add(a, b):\n' if language=='py' else '// fixed prefix: add two integers\nint add(int a, int b) {\n')
    else:t.update(problem='Return the sum of two integers a and b.',entry_point='add',subset='SecEvalPlus')
    t['public_input_sha256']=sha(json.dumps(t,sort_keys=True));return t

def solution(t):
    if 'prefix' in t:return t['prefix']+('    return a + b\n' if t['language']=='py' else '    return a + b;\n}\n')
    return 'def add(a, b):\n    return a + b\n'

def fixture(method,t):
    code=solution(t);models={}
    if method=='seccoder':models={'generation':[('    return a + b\n' if t['language']=='py' else '    return a + b;\n}\n') if 'prefix' in t else code]}
    elif method=='securecoder':models={'draft':[code],'generation':['Add two integers.','Add two integers.','Check integer input types.','Preserve the interface and return the sum.',code]}
    elif method=='rescue':models={'generation':[code,'Input validation requires checking input types.',code]}
    elif method.startswith('codexity'):models={'generation':[code]*4,'draft':[code]}
    elif method=='indict':models={'generation':[code]*9,'critic':['```python\nprint(2 + 2)\n```']*60}
    elif method=='autosafecoder':models={'generation':[code,'no vulnerabilities detected','{"a":1,"b":2}']}
    return {'responses':models,'embedding_self_index':0} if method=='securecoder' else {'responses':models}

def config(method):
    cfg=copy.deepcopy(CONFIG['methods'][method])
    if method=='indict':cfg['options']['rounds']=1
    if method=='autosafecoder':cfg['options']['iterations']=2
    return cfg

def make(method,t,name=None,dataset=None):
    out=WORK/(name or (method+'_'+str(t['index'])+'_'+t['language']))
    m=manifest(out,dataset or ('codeguard_plus' if 'prefix' in t else 'codesec_eval'),method,config(method),[t],True)
    return out,m

class Checks(unittest.TestCase):
    def test_01_all_public_inputs_and_coverage(self):
        for method in METHODS:
            for ds,n in [('codesec_eval',255),('codeguard_plus',103)]:
                ts=selected_tasks(ds,method);self.assertEqual(len(ts),n)
                for t in ts:
                    self.assertEqual(t,public_task(t));self.assertFalse(set(t)&{'Test-FP','Test-SP','Secure','Insecure','check_ql'})
        self.assertEqual(coverage(selected_tasks('codeguard_plus','autosafecoder'),'autosafecoder')['eligible'],71)
        self.assertEqual(coverage(selected_tasks('codeguard_plus','codexity_iteration'),'codexity_iteration')['eligible'],31)
        self.assertEqual(coverage(selected_tasks('codesec_eval','codexity_iteration'),'codexity_iteration')['eligible'],0)
        for method in ['seccoder','securecoder','rescue','indict']:self.assertEqual(coverage(selected_tasks('codeguard_plus',method),method)['eligible'],103)
        with self.assertRaises(ValueError):public_task({**task(),'Test-FP':'secret test'})
    def test_02_prefix_preservation_and_invalid_output(self):
        for lang in ['py','c','cpp']:
            t=task(lang,True);code=solution(t)
            self.assertEqual(candidate('```'+lang+'\n'+code+'```',t),code)
            with self.assertRaises(InvalidOutput):candidate(code.replace('fixed prefix','modified prefix'),t)
            tail=code[len(t['prefix']):];self.assertEqual(candidate(tail,t,'continuation'),code)
        with self.assertRaises(InvalidOutput):candidate('```py\nx=1\n```\n```py\nx=2\n```',task())
        with self.assertRaises(InvalidOutput):candidate('def invalid(',task())
    def test_03_models_disabled(self):
        for method in METHODS:
            with self.assertRaises(ValueError):configuration(ROOT/'config/table2/runtime.json',method,live=True)
            for role,cfg in CONFIG['methods'][method]['models'].items():self.assertIsNone(cfg['model']);self.assertIsNone(cfg['base_url'])
    def test_04_durable_model_and_nested_tool_replay(self):
        cfg=config('indict');f={'responses':{'generation':['first','last'],'search':['fact']}}
        out=WORK/'transport'
        a=Transport(cfg,out,f);self.assertEqual(a.call('generation','q1'),'first')
        a.tool('search',{'q':'q'},lambda _:a.call('search','query'))
        self.assertEqual(a.call('generation','q2'),'last')
        b=Transport(cfg,out,f);self.assertEqual(b.call('generation','q1'),'first')
        b.tool('search',{'q':'q'},lambda _:self.fail('Tool must replay'))
        self.assertEqual(b.call('generation','q2'),'last');self.assertEqual(a.counter,b.counter)
        with self.assertRaises(InfrastructureError):Transport(cfg,out,f).call('generation','different prompt')
        trunc=Transport(config('seccoder'),WORK/'truncated',{'responses':{'generation':[{'content':'x=1','finish_reason':'length'}]}})
        with self.assertRaises(InvalidOutput):trunc.call('generation','q')
    def test_05_sandbox_execution_and_isolation(self):
        control=ROOT/'runtime/table2/outside_fixture.txt';control.write_text('controlled host-only sentinel')
        code='''import os,socket
assert os.getuid()!=0
try:
 open("'''+str(control)+'''").read()
 raise AssertionError('host path was accessible')
except FileNotFoundError:pass
open('/usr/bin/forbidden-fixture','w').write('private only')
try:
 socket.socket(socket.AF_INET,socket.SOCK_STREAM)
 raise AssertionError('network was available')
except PermissionError:pass
print('ISOLATED')
'''
        result=run_python(code,WORK/'jail_isolation',timeout=5)
        self.assertTrue(result['passed'],result);self.assertIn('ISOLATED',result['stdout'])
        self.assertFalse((ROOT/'envs/benchmark-rootfs/usr/bin/forbidden-fixture').exists())
        fresh=run_python("import os; assert not os.path.exists('/usr/bin/forbidden-fixture')",WORK/'jail_fresh',5);self.assertTrue(fresh['passed'],fresh)
        self.assertTrue(run_python('def add(a,b): return a+b',WORK/'jail_ok',5,{'a':1,'b':2},'add')['passed'])
        self.assertFalse(run_python('def fail(x): raise ValueError("fixed failure")',WORK/'jail_error',5,{'x':1},'fail')['passed'])
        timed=run_python('while True: pass',WORK/'jail_timeout',1);self.assertEqual(timed['status'],'timeout')
        DETAILS['sandbox']={'isolation':result['execution']['isolation'],'uid':result['execution']['uid'],'checks':['nonroot','host_path_hidden','runtime_writes_private_and_discarded','network_denied','function_call','exception','timeout']}
    def test_06_all_method_dataset_language_workers(self):
        cases=[]
        for method in METHODS:
            if 'py' in METHODS[method]['languages']:cases.append((method,task('py',False,0),'codesec_eval'))
            for lang in METHODS[method]['languages']:cases.append((method,task(lang,True,0),'codeguard_plus'))
        for n,(method,t,ds) in enumerate(cases):
            with self.subTest(method=method,dataset=ds,language=t['language']):
                print('WORKER',method,ds,t['language'],flush=True)
                out,m=make(method,t,'worker_'+str(n),ds)
                run(out,m,{t['key']:fixture(method,t)})
                g=json.loads((out/'tasks/0000/generation.json').read_text())
                self.assertEqual(g['status'],'generated',g)
                self.assertEqual((out/'tasks/0000'/g['candidate']).read_text(),solution(t))
                response=json.loads((out/'tasks/0000/worker_response.json').read_text())
                self.assertEqual(response['network_attempts'],0)
                saved={str(f):f.stat().st_mtime_ns for f in (out/'tasks/0000/method/calls').glob('*/response.json')}
                run(out,m,{t['key']:fixture(method,t)})
                self.assertEqual(saved,{str(f):f.stat().st_mtime_ns for f in (out/'tasks/0000/method/calls').glob('*/response.json')})
                DETAILS['worker_cases'].append({'method':method,'dataset':ds,'language':t['language'],'model_calls':g['model_call_count'],'tool_calls':g['tool_call_count'],'output':str(out)})
    def test_07_unsupported_and_full_dataset_score_guard(self):
        method='codexity_iteration';ts=[task('py',True,0),task('cpp',True,1)]
        out=WORK/'unsupported';m=manifest(out,'codeguard_plus',method,config(method),ts,True);result=run(out,m)
        self.assertEqual(result['status'],'unsupported_dataset');self.assertIsNone(result['full_dataset_code_metrics'])
        self.assertEqual(result['generation']['counts'],{'unsupported_language':2})
        self.assertFalse(any(out.glob('tasks/*/worker_request.json')))
    def test_08_manifest_drift_and_candidate_tampering(self):
        t=task();out,m=make('seccoder',t,'drift');run(out,m,{t['key']:fixture('seccoder',t)})
        changed=config('seccoder');changed['models']['generation']['max_tokens']=42
        with self.assertRaises(InfrastructureError):manifest(out,'codesec_eval','seccoder',changed,[t],True)
        (out/'tasks/0000/candidate.py').write_text('changed')
        with self.assertRaises(InfrastructureError):run(out,m,{t['key']:fixture('seccoder',t)})
    def test_09_codesec_real_test_bridge_and_invalid_denominator(self):
        ts=[task('py',False,0),task('py',False,1)];out=WORK/'codesec_eval'
        m=manifest(out,'codesec_eval','seccoder',config('seccoder'),ts,True)
        good=fixture('seccoder',ts[0]);bad={'responses':{'generation':['def broken(']}}
        run(out,m,{ts[0]['key']:good,ts[1]['key']:bad})
        refs={t['key']:{'Entry_Point':'add','Test-FP':'def check(candidate):\n    assert candidate(2,3)==5','Test-SP':'def check(candidate):\n    assert candidate(-2,3)==1'} for t in ts}
        with patch.object(ev,'audit_runtime',return_value={'deferred_to_final_integrity_check':True}):result=ev.evaluate(out,refs)
        self.assertEqual(result['code_metrics']['F-Pass@1']['total'],2)
        self.assertEqual(result['code_metrics']['Joint-Pass@1']['percent'],50.0)
        before=(out/'tasks/0000/test_F/execution.json').stat().st_mtime_ns
        with patch.object(ev,'audit_runtime',return_value={'deferred_to_final_integrity_check':True}):ev.evaluate(out,refs)
        self.assertEqual(before,(out/'tasks/0000/test_F/execution.json').stat().st_mtime_ns)
    def test_10_codeguard_routing_unknown_and_recovery(self):
        t=task('py',True,7);out,m=make('autosafecoder',t,'codeguard_eval');run(out,m,{t['key']:fixture('autosafecoder',t)})
        seen=[]
        def functional(t,code,out):seen.append(t['key']);return {'passed':True}
        with patch.object(ev,'functional',side_effect=functional),patch.object(ev,'codeql',side_effect=RuntimeError('controlled analyzer outage')),patch.object(ev,'sonar_scan',return_value={t['key']:{'passed':True}}),patch.object(ev,'audit_runtime',return_value={}):result=ev.evaluate(out)
        self.assertEqual(seen,[t['key']]);self.assertIsNone(result['code_metrics']['S-Pass@1']['percent'])
        with patch.object(ev,'functional',side_effect=AssertionError('Finished functional check must not rerun')),patch.object(ev,'codeql',return_value={'applicable':True,'passed':True}),patch.object(ev,'sonar_scan',return_value={t['key']:{'passed':True}}),patch.object(ev,'audit_runtime',return_value={}):result=ev.evaluate(out)
        self.assertEqual(result['code_metrics']['Joint-Pass@1']['percent'],100.0)
    def test_11_auto_evaluate_hook(self):
        t=task();out,m=make('seccoder',t,'auto_evaluate')
        with patch.object(ev,'evaluate',return_value={}) as evaluate:
            run(out,m,{t['key']:fixture('seccoder',t)},auto_evaluate=True)
            evaluate.assert_called_once_with(out)
            self.assertTrue((out/'generation.done').exists())
    def test_12_resume_infrastructure_replays_saved_calls(self):
        t=task();out,m=make('seccoder',t,'replay_infrastructure');f=fixture('seccoder',t)
        run(out,m,{t['key']:f})
        d=out/'tasks/0000';responses={str(p):p.stat().st_mtime_ns for p in d.glob('method/calls/*/response.json')}
        g=json.loads((d/'generation.json').read_text());g.update(status='generation_error',error='controlled interruption after checkpoint');write_json(d/'generation.json',g)
        run(out,m,{t['key']:f})
        self.assertEqual(responses,{str(p):p.stat().st_mtime_ns for p in d.glob('method/calls/*/response.json')})
        reply=json.loads((d/'worker_response.json').read_text());self.assertTrue(all(x['replayed'] for x in reply['events']))
        self.assertTrue(list((d/'infrastructure_history').glob('*.json')))

    def test_13_codegen_guard_has_no_output_side_effect(self):
        out=WORK/'must_not_generate'
        p=subprocess.run(['/usr/bin/python3.10','-B','-m','table2_baselines.cli','generate','--method','seccoder','--dataset','codesec_eval','--output',str(out)],cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0);self.assertIn('Formal experiments are disabled',p.stderr);self.assertFalse(out.exists())

    def test_14_original_sources_and_runtime_unchanged(self):
        original=json.loads((SETUP/'shared-source-before.json').read_text())
        changed=[name for name,h in original.items() if sha((ROOT/name).read_bytes())!=h]
        self.assertEqual(changed,[],'Shared sources changed; investigate without rollback')
        DETAILS['runtime_integrity']=audit_runtime()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    report={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'work_directory':str(WORK),'real_generation_calls':0,'real_embedding_api_calls':0,'formal_benchmark_experiments':0,'details':DETAILS}
    write_json(SETUP/'validation.json',report);print(json.dumps(report,indent=2),flush=True)
    sys_exit=0 if report['passed'] else 1
    raise SystemExit(sys_exit)
