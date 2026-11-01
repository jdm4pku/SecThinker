"""Author prompts and prepared runtime checks; only fixed synthetic code is executed."""
import ast,contextlib,hashlib,importlib,importlib.util,importlib.metadata,io,json,os,random,socket,subprocess,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
R=Path(__file__).resolve().parents[2];S=R/'baseline/AutoSafeCoder';P=R/'src/autosafecoder_prepared'
WORK=Path(tempfile.mkdtemp(prefix='validation-',dir=R/'runs/_setup/autosafecoder_2026-10-31'))
network_attempts=[]
_original_connect=socket.socket.connect
_original_connect_ex=socket.socket.connect_ex
def allow_ipc_only(self,*args,**kwargs):
    if self.family==socket.AF_UNIX:return _original_connect(self,*args,**kwargs)
    network_attempts.append('blocked network operation');raise AssertionError('network disabled')
def allow_ipc_ex_only(self,*args,**kwargs):
    if self.family==socket.AF_UNIX:return _original_connect_ex(self,*args,**kwargs)
    network_attempts.append('blocked network operation');raise AssertionError('network disabled')
socket.socket.connect=allow_ipc_only;socket.socket.connect_ex=allow_ipc_ex_only
sys.path.insert(0,str(P))
import utils,main,executor_static,executor_agent_safe,tester_fuzz_agent

class FakeClient:
    def __init__(self,responses):
        self.responses=list(responses);self.calls=[]
        self.chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))
    def create(self,**kwargs):
        self.calls.append(kwargs)
        if not self.responses:raise AssertionError('unexpected mock LLM request')
        content=self.responses.pop(0)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
def configure(responses):
    client=FakeClient(responses);utils.configure_client(client,'OFFLINE_FIXTURE');return client
@contextlib.contextmanager
def directory(name):
    cwd=os.getcwd();d=WORK/name;d.mkdir();os.chdir(d)
    try:yield d
    finally:os.chdir(cwd)
def fixture_exec(code,inputs,timeout):
    return executor_agent_safe.execute_fuzz(code,inputs,timeout,trusted_fixture_only=True)

class Checks(unittest.TestCase):
    def tearDown(self):utils.model=None;utils._completion_client=None
    def test_01_source_and_compatibility_integrity(self):
        for f in json.loads((R/'downloads/AutoSafeCoder/source-verification.json').read_text())['files']:
            self.assertEqual(hashlib.sha256((S/f['path']).read_bytes()).hexdigest(),f['sha256'])
        for f in json.loads((R/'downloads/AutoSafeCoder/compatibility-changes.json').read_text())['files']:
            self.assertEqual(hashlib.sha256((P/f['path']).read_bytes()).hexdigest(),f['prepared_sha256'])
            ast.parse((P/f['path']).read_text())
    def test_02_dependencies_and_jwt_namespace(self):
        for module in ['openai','datasets','bandit','boto3','defusedxml','django','flask','mysql.connector','regex','flask_limiter']:importlib.import_module(module)
        import jwt
        token=jwt.encode({'fixture':True},'offline-test-key-at-least-32-bytes','HS256')
        self.assertTrue(jwt.decode(token,'offline-test-key-at-least-32-bytes',algorithms=['HS256'])['fixture'])
        self.assertEqual(jwt.__version__,'2.9.0')
        with self.assertRaises(importlib.metadata.PackageNotFoundError):importlib.metadata.version('jwt')
    def test_03_original_executor_false_pass_regression(self):
        spec=importlib.util.spec_from_file_location('original_executor_fixture',S/'executor_agent_safe.py')
        old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
        code='def controlled_failure(x):\n    raise ValueError("fixture failure")\n'
        result=old.execute_fuzz(code,{'x':1},1)
        self.assertTrue(result[1],'Pinned original regression changed; review compatibility fix')
        fixed=fixture_exec(code,{'x':1},1)
        self.assertFalse(fixed[1]);self.assertIn('fixture failure',fixed[0])
        (WORK/'executor_regression.json').write_text(json.dumps({'original':result,'prepared':fixed},indent=2))
    def test_04_executor_success_error_timeout(self):
        self.assertTrue(fixture_exec('def add(x,y):\n    return x+y',{'x':1,'y':2},1)[1])
        self.assertFalse(fixture_exec('def div(x):\n    return 1/x',{'x':0},1)[1])
        timed=fixture_exec('def spin(x):\n    while True: pass',{'x':1},0.2)
        self.assertFalse(timed[1]);self.assertEqual(timed[0],'timed out')
    def test_05_real_bandit_positive_and_negative(self):
        a=executor_static.ExecutorStaticAgent({})
        bad=a.execute_static_analysis('def evaluate(value):\n    return eval(value)\n')
        good=a.execute_static_analysis('def add(x,y):\n    return x+y\n')
        self.assertEqual(bad[0].name,'ERROR');self.assertTrue(bad[1].startswith('CWE-'))
        self.assertEqual(good[0].name,'SAFE')
        (WORK/'bandit_controls.json').write_text(json.dumps({'bad':[bad[0].name,*bad[1:]],'good':[good[0].name,*good[1:]]},indent=2))
    def test_06_bandit_errors_not_safe(self):
        a=executor_static.ExecutorStaticAgent({})
        self.assertEqual(a.execute_static_analysis('def broken(')[0].name,'FAILURE')
        with patch.object(executor_static.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout='invalid JSON',stderr='')):
            self.assertEqual(a.execute_static_analysis('x=1')[0].name,'FAILURE')
        with patch.object(executor_static.subprocess,'run',side_effect=OSError('missing tool')):
            self.assertEqual(a.execute_static_analysis('x=1')[0].name,'FAILURE')
        with patch.object(executor_static.subprocess,'run',side_effect=subprocess.TimeoutExpired('bandit',6)):
            self.assertEqual(a.execute_static_analysis('x=1')[0].name,'TIMED_OUT')
    def test_07_mutation_repeatability(self):
        original={'x':1,'flag':True,'items':['abc',2.2]};before=json.loads(json.dumps(original))
        random.seed(42);one=utils.mutate_inputs(original)
        random.seed(42);two=utils.mutate_inputs(original)
        self.assertEqual(one,two);self.assertEqual(original,before);self.assertNotEqual(one,original)
    def test_08_tester_retries(self):
        c=configure(['not JSON','also not JSON','json\n{"x":1}'])
        self.assertEqual(tester_fuzz_agent.TesterFuzzAgent({'Prompt':'fixture'}).generate_test_inputs(),{'x':1})
        self.assertEqual(len(c.calls),3)
        c=configure(['invalid']*3)
        self.assertEqual(tester_fuzz_agent.TesterFuzzAgent({'Prompt':'fixture'}).generate_test_inputs(),{})
        self.assertEqual(len(c.calls),3)
    def test_09_pipeline_static_repair(self):
        code='def add(x,y):\n    return x+y'
        c=configure([code,'CWE-20 fixture review',code,'no vulnerabilities detected','{"x":1,"y":2}'])
        with directory('static_flow') as d,patch.object(main,'execute_fuzz',side_effect=fixture_exec),contextlib.redirect_stdout(io.StringIO()):
            main.MultiAgentSystem({'ID':'synthetic','Prompt':'Add two integers.'}).run(iterations=2)
            out=json.loads((d/'results.json').read_text())
        self.assertEqual(out['static_analysis_status'],'fixed 1');self.assertEqual(out['fuzzing_test_status'],'success')
        self.assertEqual(len(c.calls),5);self.assertFalse(c.responses)
        self.assertIn('code security analyzer',c.calls[1]['messages'][0]['content'])
    def test_10_pipeline_replays_failed_input(self):
        c=configure(['def div(x):\n    return 1/x','no vulnerabilities detected','{"x":0}','def div(x):\n    return 0 if x == 0 else 1/x'])
        seen=[]
        def execute(code,inputs,timeout):
            seen.append(dict(inputs));return fixture_exec(code,inputs,timeout)
        with directory('fuzz_repair') as d,patch.object(main,'execute_fuzz',side_effect=execute),patch.object(main.InputMutatorAgent,'mutate_inputs',return_value={'x':999}),contextlib.redirect_stdout(io.StringIO()):
            main.MultiAgentSystem({'ID':'synthetic','Prompt':'Return a bounded reciprocal.'}).run(iterations=1)
            out=json.loads((d/'results.json').read_text())
        self.assertEqual(seen,[{'x':0},{'x':0}]);self.assertEqual(out['fuzzing_test_status'],'fixed 1')
        self.assertEqual(len(c.calls),4)
    def test_11_no_inputs_is_not_tested(self):
        c=configure(['def f(x): return x','no vulnerabilities detected','invalid','invalid','invalid'])
        with directory('missing_inputs') as d,contextlib.redirect_stdout(io.StringIO()):
            main.MultiAgentSystem({'ID':'synthetic','Prompt':'fixture'}).run(iterations=1)
            out=json.loads((d/'results.json').read_text())
        self.assertEqual(out['fuzzing_test_status'],'No inputs created')
        self.assertEqual(len(c.calls),5)
    def test_12_models_and_host_execution_disabled(self):
        c=json.loads((R/'config/autosafecoder/runtime.json').read_text())
        for key in ['generation_model','static_reviewer_model','test_input_model','endpoint','static_analysis_mode']:self.assertIsNone(c[key])
        self.assertFalse(c['formal_experiments_enabled'])
        with self.assertRaises(RuntimeError):utils.request_completion(messages=[])
        with self.assertRaises(ValueError):utils.configure_client(None,None)
        with self.assertRaises(RuntimeError):executor_agent_safe.execute_fuzz('def f(x): return x',{'x':1},1)
    def test_13_author_prompts_and_dataset(self):
        self.assertEqual(utils.construct_few_shot_prompt,(S/'prompts_fewshot/coder_agent_prompt.txt').read_text())
        self.assertEqual(utils.construct_few_shot_prompt_fuzz,(S/'prompts_fewshot/initial_inputs_prompt.txt').read_text())
        data=[json.loads(x) for x in (S/'dataset copy.jsonl').read_text().splitlines() if x.strip()]
        self.assertTrue(data);self.assertTrue(all('ID' in x and 'Prompt' in x for x in data))
        (WORK/'author_dataset.json').write_text(json.dumps({'count':len(data),'used_for_generation':False}))

result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
report={'baseline':'AutoSafeCoder','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful() and not network_attempts,'network_attempts':len(network_attempts),'real_model_calls':0,'formal_benchmark_tasks':0,'work_directory':str(WORK),'limitations':['Only Python supported by author prompts/fuzzer/Bandit','Official main uses LLM static review; Bandit is a separate path','Prepared corrections documented; unmodified author executor falsely passed a raising function','Formal generated-code execution requires sandbox backend injection','Project benchmark input/output/evaluation adapter pending']}
(R/'runs/_setup/autosafecoder_2026-10-31/validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));sys.exit(0 if report['passed'] else 1)
