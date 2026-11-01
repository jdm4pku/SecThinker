import ast,hashlib,json,re
from pathlib import Path
from prompt_baselines.core import tasks,now,task_definition
from secthinker_experiments.artifacts import write_json
from .registry import ROOT,METHODS,DATASETS
class InfrastructureError(RuntimeError):pass
class InvalidOutput(ValueError):pass

def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def project_path(value):
    p=Path(value).resolve()
    if not p.is_relative_to(ROOT):raise ValueError('Path outside project')
    return p

def public_task(t):
    allowed={'key','index','subset','language','problem','entry_point','prefix','public_input_sha256'}
    if set(t)-allowed:raise ValueError('Task contains fields outside public input schema')
    if ('problem' in t)==('prefix' in t):raise ValueError('Expected exactly one public problem or source prefix')
    return dict(t)

def selected_tasks(dataset,method):
    if dataset not in DATASETS or method not in METHODS:raise ValueError('Unknown dataset/method')
    return [public_task(t) for t in tasks(dataset)]

def body(raw):
    if not isinstance(raw,str) or not raw.strip():raise InvalidOutput('empty_output')
    blocks=re.findall(r'```[^\n]*\n(.*?)```',raw,re.S)
    if len(blocks)>1:raise InvalidOutput('ambiguous_code_blocks')
    return blocks[0] if blocks else raw

def candidate(raw,t,mode='full'):
    code=body(raw)
    if 'prefix' in t:
        prefix=t['prefix']
        if not code.startswith(prefix):
            code=code.strip('\r\n')
            if code.startswith(prefix):pass
            elif mode=='continuation':code=prefix+('' if prefix.endswith('\n') else '\n')+code
            else:raise InvalidOutput('modified_or_missing_original_prefix')
        if not code.startswith(prefix):raise InvalidOutput('prefix_integrity_failed')
    else:code=code.strip('\r\n')
    if not code.endswith('\n'):code+='\n'
    if t['language']=='py':
        try:ast.parse(code)
        except SyntaxError as e:raise InvalidOutput('syntax_error:'+str(e)) from e
    return code

def instruction(t):
    text=task_definition(t)
    if 'prefix' in t:
        text+='\nReturn the COMPLETE source file in a single code block. Preserve every byte of the supplied prefix, including comments, whitespace, imports and function signature. Append the missing implementation only. Do not include a demonstration.\n'
    else:text+='\nReturn a complete Python implementation with required imports in one code block, implementing the required entry point.\n'
    return text

def coverage(ts,method):
    supported=METHODS[method]['languages'];counts={}
    for t in ts:counts[t['language']]=counts.get(t['language'],0)+1
    eligible=sum(t['language'] in supported for t in ts)
    return {'selected':len(ts),'eligible':eligible,'unsupported':len(ts)-eligible,'language_counts':counts,'supported_languages':supported,'unsupported_languages':{k:v for k,v in counts.items() if k not in supported},'full_dataset_comparable':eligible==len(ts)}

def configuration(path,method,live=False):
    cfg=json.loads(project_path(path).read_text());m=cfg['methods'][method]
    if live:
        if not cfg.get('formal_experiments_enabled'):raise ValueError('Formal experiments are disabled; generation models have not been selected')
        for role in METHODS[method]['roles']:
            c=m['models'][role]
            if not c.get('model') or not c.get('base_url'):raise ValueError('Missing explicit '+role+' model/base_url')
            if not c.get('max_tokens',1)>0:raise ValueError('Invalid output budget')
        if method=='seccoder' and not m['options'].get('retrieval_pack'):raise ValueError('Select tokenizer/context and build a frozen retrieval pack first')
        if method=='seccoder' and not re.fullmatch(r'[0-9a-f]{64}',m['options'].get('retrieval_pack_sha256','')):raise ValueError('Freeze the retrieval pack SHA256 before generation')
        if method=='securecoder' and m['models']['embedding']['model']!='text-embedding-ada-002':raise ValueError('Bundled SecureCoder index requires author-compatible embedding model')
        if method=='indict' and not m['options'].get('live_search_enabled'):raise ValueError('INDICT external search is not enabled/configured')
    return cfg,m
