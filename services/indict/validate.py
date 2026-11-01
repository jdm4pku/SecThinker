"""Offline checks of pinned author source. Does not expose a generation command."""
import ast,hashlib,importlib,importlib.metadata,json,os,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'baseline/INDICT'
WORK=Path(tempfile.mkdtemp(prefix='validation-',dir=ROOT/'runs/_setup/indict_2026-10-31'))
network_attempts=[]
def deny(*args,**kwargs):
    network_attempts.append('blocked network operation')
    raise AssertionError('network disabled during offline validation')
socket.socket.connect=deny
socket.create_connection=deny
socket.getaddrinfo=deny
os.environ['OPENAI_API_KEY']='offline-test-placeholder-not-a-credential'
os.environ['OPENAI_BASE_URL']='http://127.0.0.1:9/v1'
sys.path.insert(0,str(SOURCE))
import tools,agents,configs,util,llm

class FakeLLM:
    def __init__(self):self.calls=[]
    def query_with_retries(self,prompt,**kwargs):
        self.calls.append({'prompt':prompt,'kwargs':kwargs})
        if prompt.startswith('OFFLINE_TOOL_TEMPLATE:'):
            name='code_review' if 'code_review' in prompt else 'code_search'
            param='code' if name=='code_review' else 'snippet'
            return json.dumps([{'tool_name':name,'parameters':{'query':'controlled fixture',param:'print(2 + 2)'}}])
        return '```python\nprint(2 + 2)\n```'
class FakeTokenizer:
    def apply_tool_use_template(self,conversation,tools,**kwargs):
        return 'OFFLINE_TOOL_TEMPLATE:'+tools[0]['name']+conversation[0]['content']

def make_agent(language,strategy='indict_llama',prev_trial=None):
    model=FakeLLM()
    a=agents.Agents(0,'Write a function to add two integers.',
        action_llm=model,critic_llm=model,programming_language=language,task='instruct',
        critic_tool=[configs.tool_definitions['codesearch']],
        critic_tool_posthoc=[configs.tool_definitions['codereview']],
        tokenizer=FakeTokenizer(),prev_trial=prev_trial,**configs.agent_configs[strategy])
    return a,model

def run_mock(language,strategy='indict_llama',prev_trial=None):
    a,m=make_agent(language,strategy,prev_trial)
    facts=[{'title':'offline fixture','description':'mock supporting fact','source':'mock'}]
    with patch.object(tools,'code_search',return_value=facts) as search,patch.object(tools,'code_review',return_value=facts) as review,patch.object(tools,'run_code',return_value='4\n') as run:
        out=a.run(getattr(agents.AgentStrategy,configs.strategy_mapping[strategy]))
    return out,m,search.call_count,review.call_count,run.call_count

class Checks(unittest.TestCase):
    def test_01_source_integrity(self):
        manifest=json.loads((ROOT/'downloads/INDICT/source-verification.json').read_text())
        for f in manifest['files']:
            self.assertEqual(hashlib.sha256((SOURCE/f['path']).read_bytes()).hexdigest(),f['sha256'],f['path'])
        for f in SOURCE.glob('*.py'):ast.parse(f.read_text(),filename=str(f))
    def test_02_runtime_imports(self):
        for name in ['numpy','pandas','sklearn','scipy','datasets','matplotlib','transformers','tiktoken','wikipedia','search_engine_parser','langchain_experimental']:
            importlib.import_module(name)
        self.assertEqual(importlib.metadata.version('openai'),'1.3.6')
    def test_03_controlled_interpreter(self):
        self.assertEqual(tools.run_code('print(2 + 2)').strip(),'4')
        self.assertIn('ZeroDivisionError',tools.run_code('print(1 / 0)'))
    def test_04_python_pipeline(self):
        out,m,s,r,e=run_mock('python')
        self.assertEqual((len(m.calls),s,r,e),(17,2,2,1))
        for key in ['action','initial_action','mid_action','critic','critic_posthoc','safety_tool_output_posthoc','helpful_critics_posthoc']:
            self.assertIn(key,out)
        (WORK/'python_mock_round1.json').write_text(json.dumps(out,indent=2))
    def test_05_c_pipeline(self):
        out,m,s,r,e=run_mock('c')
        self.assertEqual((len(m.calls),s,r,e),(9,2,0,0))
        self.assertNotIn('critic_posthoc',out)
        (WORK/'c_mock_round1.json').write_text(json.dumps(out,indent=2))
    def test_06_three_round_continuation(self):
        previous=None
        for n in range(3):
            out,m,s,r,e=run_mock('python',prev_trial=previous)
            self.assertEqual(len(m.calls),17 if n==0 else 16)
            previous=str(WORK/f'continuation_round{n+1}.json')
            Path(previous).write_text(json.dumps(out,indent=2))
        self.assertEqual(len(out['critic']),3)
        self.assertEqual(len(out['critic_posthoc']),3)
    def test_07_commandr_branch_mock_tokenizer(self):
        out,m,s,r,e=run_mock('python','indict_commandr')
        self.assertEqual((len(m.calls),s,r,e),(13,2,2,1))
        self.assertIn('mock supporting fact',out['safety_critics'][0])
    def test_08_tool_combination_and_parsers(self):
        with patch.object(tools,'query_openai',return_value={'description':'one'}),patch.object(tools,'internet_search',return_value={'description':'two'}),patch.object(tools,'query_wikipedia',return_value={'description':'three'}):
            self.assertEqual([i['source'] for i in tools.query_all_tools('q','q')],['chatgpt','internet','wikipedia'])
        self.assertTrue(tools.invalid_response(None))
        self.assertTrue(tools.invalid_response({'description':'I cannot answer'}))
        self.assertEqual(util.extract_tools('```json\n[{"tool_name":"code_search"}]\n```')[0]['tool_name'],'code_search')
        self.assertEqual(util.extract_tools('not json'),[])
    def test_09_official_demo_loaders(self):
        previous=os.getcwd()
        try:
            os.chdir(SOURCE)
            counts={}
            for task in ['mitre','instruct','autocomplete','promptinject','interpreter','cvs']:
                data,header,key=util.load_data(task)
                self.assertGreater(len(data),0)
                self.assertTrue(all(key in row for row in data))
                counts[task]=len(data)
            (WORK/'demo_counts.json').write_text(json.dumps(counts,indent=2))
        finally:os.chdir(previous)
    def test_10_sdk_transport_without_network(self):
        import httpx,openai
        def respond(request):
            body=json.loads(request.content)
            self.assertEqual(body['model'],'OFFLINE_FIXTURE')
            return httpx.Response(200,json={'id':'offline','object':'chat.completion','created':0,'model':'OFFLINE_FIXTURE','choices':[{'index':0,'message':{'role':'assistant','content':'fixture response'},'finish_reason':'stop'}]})
        model=llm.OPENAI('OFFLINE_FIXTURE','offline-placeholder',base_url='http://127.0.0.1:9/v1')
        model.client.close()
        model.client=openai.OpenAI(api_key='offline-placeholder',base_url='http://127.0.0.1:9/v1',http_client=httpx.Client(transport=httpx.MockTransport(respond)))
        self.assertEqual(model.query('fixture'),'fixture response')
        model.client.close()
    def test_11_no_model_selected(self):
        c=json.loads((ROOT/'config/indict/runtime.json').read_text())
        for key in ['actor_model','critic_model','search_llm_model','endpoint','strategy']:self.assertIsNone(c[key])
        self.assertFalse(c['formal_experiments_enabled'])
        self.assertFalse(c['live_tools_enabled'])

result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
report={'baseline':'INDICT','tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful() and not network_attempts,'network_attempts':len(network_attempts),'real_model_calls':0,'formal_benchmark_tasks':0,'work_directory':str(WORK),'limitations':['Yahoo/Wikipedia/OpenAI live tools untested; models/endpoints unset','Execution is mocked in agent tests; only constant print/error snippets execute in the real REPL','CommandR template API is mocked, no tokenizer weights selected','No CodeSecEval/CodeGuard+ input/output/evaluation adapter yet','Upstream prompt_critic_agent drops query argument; Wikipedia exception handler refers to undefined e; frr data loader absent']}
(ROOT/'runs/_setup/indict_2026-10-31/validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
sys.exit(0 if report['passed'] else 1)
