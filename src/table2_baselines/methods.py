"""Bridge author algorithms to public benchmark inputs and the shared transport."""
import contextlib,hashlib,json,os,random,re,sys,tempfile,types
from pathlib import Path
from unittest.mock import patch
from .registry import ROOT
from .common import candidate,instruction,InvalidOutput,InfrastructureError,write_json,project_path
from .sandbox import run_python

def seccoder(t,tr,options):
    from seccoder_baseline.prompts import compose,build_prompt,read_pack
    if tr.fixture is not None:
        prompt=compose(t,tr.fixture.get('demonstration','def identity(value):\n    return value\n'))
    else:
        path=project_path(options['retrieval_pack'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=options.get('retrieval_pack_sha256'):
            raise InfrastructureError('Frozen retrieval pack checksum changed')
        pack,_=read_pack(str(path))
        if pack.get('is_test_fixture'):raise InfrastructureError('Synthetic retrieval packs cannot be used for formal runs')
        tok=project_path(pack['tokenizer_dir'])
        for filename,digest in pack['tokenizer_files_sha256'].items():
            if hashlib.sha256((tok/filename).read_bytes()).hexdigest()!=digest:raise InfrastructureError('Generator tokenizer changed since retrieval')
        if tr.config['models']['generation']['max_tokens']>pack['max_tokens']:raise InfrastructureError('Output budget exceeds frozen retrieval budget')
        if not tr.config['models']['generation'].get('disable_native_thinking'):raise InfrastructureError('SecCoder frozen retrieval protocol requires disable_native_thinking')
        prompt=build_prompt(t,'seccoder_xl',str(path),options['dataset'])
    raw=tr.call('generation',prompt)
    return {'candidate':candidate(raw,t,'continuation'),'raw_final_response':raw,'retrieval':options.get('retrieval_pack'),'prompt_protocol':'existing_seccoder_top1'}

def securecoder(t,tr,options):
    from securecoder_baseline.pipeline import load_knowledge,run_pipeline
    from langchain_core.embeddings import Embeddings
    from langchain_core.runnables import RunnableLambda
    class Embed(Embeddings):
        def embed_documents(self,texts):return [self.embed_query(x) for x in texts]
        def embed_query(self,text):return tr.embedding(text)
    knowledge=load_knowledge(Embed())
    if tr.fixture is not None and tr.fixture.get('embedding_self_index') is not None:
        tr.fixture.setdefault('responses',{})['embedding']=[knowledge.index.reconstruct(tr.fixture['embedding_self_index']).tolist()]
    raw=tr.call('draft',instruction(t));draft=candidate(raw,t)
    write_json(tr.output/'initial_draft.json',{'raw':raw,'candidate':draft,'protocol':'public task draft, separate recorded model role'})
    try:result=run_pipeline(draft,RunnableLambda(lambda prompt:tr.call('generation',prompt.to_string())),knowledge)
    except ValueError as e:
        if str(e) in ['Ambiguous multiple code blocks','Empty code output','Empty code block']:raise InvalidOutput(str(e)) from e
        raise
    result['candidate']=candidate(result['raw_final_response'],t)
    return result

def rescue(t,tr,options):
    from rescue_baseline.runtime import initialize
    h=initialize()
    # Reuse the previously validated immutable BGE index arrays when available.
    report_path=ROOT/'runs/_setup/rescue_2026-10-31/validation.json'
    cache=ROOT/'runs/_setup/rescue_2026-10-31/knowledge-indices.npz'
    if cache.exists() and report_path.exists():
        report=json.loads(report_path.read_text())
        if hashlib.sha256(cache.read_bytes()).hexdigest()==report['details']['knowledge_indices_sha256']:
            import numpy as np
            with np.load(cache) as data:
                for attr,prefix in [('_SLICED_CODE_DENSE_INDEX','code'),('_VULN_TEXT_DENSE_INDEX','cause'),('_CWE_LEVEL_VULN_INDEX','cwe_cause')]:
                    setattr(h,attr,{'python':data[prefix+'_python'].copy(),'c':data[prefix+'_c'].copy()})
    from src.baselines import zero_shot
    from src.rescue import augmented_code_generation as generation,augmented_prompt
    from src.common import const,zero_shot_prompt,utils
    alias='__TABLE2_CONFIGURED_CHAT__';const.CHAT_MODELS.add(alias)
    class Model:
        def chat_complete(self,prompt,system_prompt=None,**kwargs):
            messages=([{'role':'system','content':system_prompt}] if system_prompt else [])+[{'role':'user','content':prompt}]
            return tr.call('generation',messages),None
        def completion(self,*a,**kw):raise InfrastructureError('Explicit chat protocol expected')
    def builder(code,knowledge,language):
        return 'Given the following retrieved security knowledge:\n```markdown\n'+knowledge+'\n```\n\n'+instruction(t)
    args={'model_name':alias,'benchmark':'Table2','language':t['language'],'code_snippet':t.get('prefix',instruction(t))}
    # Replace only benchmark prompt/response integration, retaining author retrieval and thresholds.
    with patch.object(h,'load_model',return_value=Model()),patch.object(zero_shot,'load_model',return_value=Model()),patch.object(generation,'load_model',return_value=Model()),patch.dict(zero_shot_prompt.BENCHMARK_PROMPT_BUILDERS,{'Table2':(lambda _:instruction(t),lambda _:instruction(t))}),patch.dict(augmented_prompt.AUGMENTED_PROMPT_OVERRIDES,{'Table2':{alias:builder}}),patch.object(utils,'get_completion_generated_result',side_effect=lambda response,*a:candidate(response,t)),patch.object(utils,'get_the_code',side_effect=lambda response,*a:candidate(response,t)):
        result=generation.run(args)
    result.update(candidate=candidate(result['final_prediction'],t),raw_final_response=result['final_prediction'],prompt_protocol='chat_public_task_v1; original retrieval; explicit benchmark adaptation')
    return result

def codexity(t,tr,options,preshot=False):
    from codexity_baseline.prompts import prompt
    from codexity_baseline.analyzers import analyze,feedback
    strategy='preshot' if preshot else 'iteration'
    def check(code):
        def run(out):
            result=analyze(code,out,language='c',strategy=strategy)
            if result['status']=='tool_error':raise InfrastructureError('Codexity tool error: '+str(out))
            return result
        return tr.tool('sast',{'code':code,'strategy':strategy},run)
    if preshot:
        raw=tr.call('draft','Complete the code:\n'+instruction(t));draft=candidate(raw,t);report=check(draft)
        if report['status']=='invalid_code':raise InvalidOutput('Invalid C draft')
        mode='preshot' if report['findings'] else 'preshot_clean'
        raw=tr.call('generation',prompt(mode,instruction(t),feedback(report),draft));code=candidate(raw,t)
        return {'candidate':code,'raw_final_response':raw,'draft':draft,'analysis':report,'strategy':strategy}
    limit=options.get('max_repairs',3)
    if not 0<=limit<=3:raise ValueError('Codexity permits at most three repairs')
    messages=prompt('initial',instruction(t));rounds=[]
    for i in range(limit+1):
        raw=tr.call('generation',messages);code=candidate(raw,t);report=check(code)
        rounds.append({'round':i,'candidate':code,'analysis':report})
        if report['status']=='invalid_code':raise InvalidOutput('Invalid C candidate')
        if report['status']=='no_findings':break
        messages=prompt('repair',code,feedback(report))
    return {'candidate':code,'raw_final_response':raw,'rounds':rounds,'strategy':strategy}

def indict(t,tr,options):
    if options.get('strategy')!='indict_llama':raise ValueError('Integrated strategy is generic text-tool INDICT; CommandR is not silently substituted')
    count=options.get('rounds',3)
    if not 1<=count<=3:raise ValueError('Expected one to three INDICT rounds')
    old={k:os.environ.get(k) for k in ['OPENAI_API_KEY','OPENAI_BASE_URL']}
    os.environ['OPENAI_API_KEY']='unused-import-placeholder';os.environ['OPENAI_BASE_URL']='http://127.0.0.1:9/v1'
    sys.path.insert(0,str(ROOT/'baseline/INDICT'))
    try:import agents,configs,tools
    finally:
        for k,v in old.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v
    errors=[];actor_raw=[]
    class Model:
        def __init__(self,role):self.role=role
        def query_with_retries(self,prompt,stop_seqs=None,max_tokens=1024,**kwargs):
            raw=tr.call(self.role,prompt,max_tokens,stop_seqs)
            if self.role=='generation':
                actor_raw.append(raw);return '```'+('python' if t['language']=='py' else t['language'])+'\n'+candidate(raw,t)+'```'
            return raw
    def isolated(code):
        report=tr.tool('python',{'code':code},lambda out:run_python(code,out,timeout=30))
        return report.get('stdout','')+('' if report['passed'] else '\n'+report.get('error_type',report['status'])+': '+report.get('error',''))
    def search(query,snippet=None,code=None):
        try:
            context=snippet if snippet is not None else code
            observation=isolated(code) if code else ''
            combined='Code context:\n'+(context or '')+'\nObservation:\n'+observation+'\nQuery: '+str(query)
            def run(out):
                if tr.fixture is not None:return [{'title':'offline fixture','description':'controlled tool evidence','source':'fixture'}]
                sources=options.get('search_sources',[]);results=[]
                for source in sources:
                    if source=='llm':result={'title':query,'description':tr.call('search',combined,max_tokens=256)}
                    elif source=='yahoo':result=tools.internet_search(combined)
                    elif source=='wikipedia':
                        description=tools.wikipedia_api.search(query)
                        result={'title':query,'description':description}
                    else:raise InfrastructureError('Unknown INDICT search source')
                    if result is None:raise InfrastructureError('External search tool unavailable: '+source)
                    if not tools.invalid_response(result):results.append({**result,'source':source})
                return results
            return tr.tool('search',{'query':query,'context':context,'observation':observation},run)
        except Exception as e:errors.append(e);raise
    # Original query_tools swallows tool exceptions: propagate infrastructure failures after its call.
    original_query=agents.Agents.query_tools
    def guarded_query(self,*a,**kw):
        result=original_query(self,*a,**kw)
        if errors:raise errors[-1]
        return result
    # Preserve the actual query in the code-example prompt (upstream accidentally passes None).
    def critic_prompt(self,llm_module,prompt_template,fewshots='',max_tokens=1024,stop_seqs=None,answer=None,query=None):
        prompt=self._build_critic_agent_prompt(prompt_template,fewshots,answer,query=query)
        return llm_module.query_with_retries(prompt,max_tokens=max_tokens,stop_seqs=stop_seqs).strip()
    previous=None;rounds=[]
    with patch.object(tools,'run_code',side_effect=isolated),patch.object(tools,'code_search',side_effect=search),patch.object(tools,'code_review',side_effect=search),patch.object(agents.Agents,'query_tools',guarded_query),patch.object(agents.Agents,'prompt_critic_agent',critic_prompt):
        for i in range(count):
            a=agents.Agents(t['index'],instruction(t),action_llm=Model('generation'),critic_llm=Model('critic'),programming_language='python' if t['language']=='py' else t['language'],task='instruct',critic_tool=[configs.tool_definitions['codesearch']],critic_tool_posthoc=[configs.tool_definitions['codereview']],prev_trial=previous,**configs.agent_configs['indict_llama'])
            result=a.run(agents.AgentStrategy.INDICT_LLAMA);rounds.append(result)
            previous=str(tr.output/f'indict_round{i+1}.json');write_json(previous,result)
    return {'candidate':candidate(result['action'],t),'raw_final_response':actor_raw[-1],'rounds':rounds,'strategy':'indict_llama','posthoc':t['language']=='py'}

def autosafecoder(t,tr,options):
    if options.get('static_mode')!='author_llm':raise ValueError('Select the author LLM static-review protocol explicitly')
    if options.get('max_repairs')!=4:raise ValueError('Prepared author flow uses four repair attempts')
    iterations=options.get('iterations',120)
    if not 1<=iterations<=120:raise ValueError('Invalid fuzz iteration budget')
    sys.path.insert(0,str(ROOT/'src/autosafecoder_prepared'))
    import utils,main
    errors=[];raws=[]
    class Client:
        def __init__(self):self.chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))
        def create(self,**kwargs):
            try:raw=tr.call('generation',kwargs['messages']);raws.append(raw)
            except Exception as e:errors.append(e);raise
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=raw))])
    utils.configure_client(Client(),tr.config['models']['generation']['model'] or 'OFFLINE_FIXTURE')
    entry={'ID':t['key'],'Prompt':instruction(t)};system=main.MultiAgentSystem(entry)
    for name in ['write_code','write_code_feedback_static','write_code_feedback_fuzz']:
        original=getattr(system.programmer_agent,name)
        def checked(*a,_original=original,**kw):
            code=_original(*a,**kw)
            if errors:raise errors[-1]
            return candidate(code,t)
        setattr(system.programmer_agent,name,checked)
    entry_name=t.get('entry_point')
    if not entry_name and 'prefix' in t:
        matches=re.findall(r'^\s*def\s+(\w+)\s*\(',t['prefix'],re.M)
        if matches:entry_name=matches[-1]
    def execute(code,inputs,timeout):
        if errors:raise errors[-1]
        report=tr.tool('fuzz',{'code':code,'inputs':inputs,'entry':entry_name},lambda out:run_python(code,out,timeout=timeout,inputs=inputs,entry=entry_name))
        status='passed' if report['passed'] else ('timed out' if report['status']=='timeout' else 'failed: '+report.get('error','Process error'))
        return status,report['passed'],inputs,entry_name
    random.seed(tr.config['models']['generation'].get('seed',42)+t['index'])
    workspace=Path(tempfile.mkdtemp(prefix='autosafecoder-',dir=tr.output));previous=os.getcwd()
    try:
        os.chdir(workspace)
        with patch.object(main,'execute_fuzz',side_effect=execute):system.run(iterations=iterations)
    finally:os.chdir(previous)
    if errors:raise errors[-1]
    result=json.loads((workspace/'results.json').read_text().splitlines()[-1])
    if result['fuzzing_test_status']=='error running function':raise InfrastructureError('AutoSafeCoder dynamic executor failed')
    result.update(candidate=candidate(system.code,t),raw_final_response=system.code)
    return result

def dispatch(method,t,tr,options):
    if method=='codexity_iteration':return codexity(t,tr,options)
    if method=='codexity_preshot':return codexity(t,tr,options,preshot=True)
    return globals()[method](t,tr,options)
