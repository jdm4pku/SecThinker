"""Model-injected transport with exact-request durable checkpoints and no defaults."""
import json,os,time,urllib.error,urllib.request
from pathlib import Path
from .common import sha,canonical,write_json,now,InfrastructureError,InvalidOutput,project_path

class Transport:
    def __init__(self,config,output,fixture=None):
        self.config=config;self.output=project_path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.fixture=fixture;self.counter=0;self.role_counts={};self.tool_counter=0;self.events=[]
    def call(self,role,prompt,max_tokens=None,stop=None):
        messages=prompt if isinstance(prompt,list) else [{'role':'user','content':prompt}]
        return self._request(role,{'messages':messages},max_tokens,stop)
    def embedding(self,text):return self._request('embedding',{'input':text})
    def _request(self,role,content,max_tokens=None,stop=None):
        cfg=self.config['models'].get(role)
        if cfg is None:raise InfrastructureError('Unknown model role: '+role)
        if self.fixture is None and (not cfg.get('model') or not cfg.get('base_url')):raise InfrastructureError('Unconfigured model: '+role)
        self.counter+=1
        if self.counter>256:raise InfrastructureError('Model call budget exceeded')
        role_index=self.role_counts.get(role,0);self.role_counts[role]=role_index+1
        payload={'model':cfg['model'] or ('OFFLINE_FIXTURE_'+role),**content}
        if role!='embedding':
            payload.update(temperature=cfg.get('temperature',0),top_p=cfg.get('top_p',1),seed=cfg.get('seed',42),max_tokens=min(max_tokens or cfg['max_tokens'],cfg['max_tokens']),n=1,stream=False)
            if stop:payload['stop']=stop
            if cfg.get('disable_native_thinking'):payload['chat_template_kwargs']={'enable_thinking':False}
        key=f'{self.counter:04d}_{role}';d=self.output/'calls'/key;d.mkdir(parents=True,exist_ok=True)
        request={'role':role,'base_url':cfg.get('base_url'),'payload':payload,'validation_only':self.fixture is not None}
        identity=sha(canonical(request));rp=d/'request.json';response=d/'response.json'
        if rp.exists() and json.loads(rp.read_text())!=request:raise InfrastructureError('Checkpoint request changed: '+key)
        if not rp.exists():write_json(rp,request)
        replayed=response.exists()
        if replayed:
            record=json.loads(response.read_text())
            if record['request_sha256']!=identity:raise InfrastructureError('Checkpoint identity mismatch')
            data=record['response']
            if sha(canonical(data))!=record['response_sha256']:raise InfrastructureError('Checkpoint response modified')
        elif self.fixture is not None:
            replies=self.fixture.get('responses',{}).get(role,[])
            if role_index>=len(replies):raise InfrastructureError('No mock reply for '+role+':'+str(role_index))
            reply=replies[role_index]
            if isinstance(reply,dict) and 'raise' in reply:raise InfrastructureError(reply['raise'])
            if role=='embedding':data={'data':[{'index':0,'embedding':reply}]}
            else:
                finish=reply.get('finish_reason','stop') if isinstance(reply,dict) else 'stop'
                raw=reply['content'] if isinstance(reply,dict) else reply
                data={'choices':[{'index':0,'message':{'role':'assistant','content':raw},'finish_reason':finish}],'usage':{}}
            write_json(response,{'received_at':now(),'request_sha256':identity,'response_sha256':sha(canonical(data)),'response':data,'validation_only':True})
        else:
            token=None
            if cfg.get('api_key_env'):
                token=os.environ.get(cfg['api_key_env'])
                if not token:raise InfrastructureError('Missing credential environment variable: '+cfg['api_key_env'])
            headers={'Content-Type':'application/json'}
            if token:headers['Authorization']='Bearer '+token
            endpoint=cfg['base_url'].rstrip('/')+('/embeddings' if role=='embedding' else '/chat/completions')
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(3):
                try:
                    req=urllib.request.Request(endpoint,data=json.dumps(payload).encode(),headers=headers)
                    with opener.open(req,timeout=600) as stream:data=json.load(stream)
                    if role=='embedding':data['data'][0]['embedding']
                    else:data['choices'][0]['message'];data['choices'][0]['finish_reason']
                    write_json(response,{'received_at':now(),'request_sha256':identity,'response_sha256':sha(canonical(data)),'response':data,'validation_only':False})
                    break
                except Exception as e:
                    write_json(d/f'error.{time.time_ns()}.json',{'time':now(),'error':repr(e)})
                    if attempt==2 or isinstance(e,urllib.error.HTTPError) and e.code not in (408,429,500,502,503,504):raise InfrastructureError('Model transport failed: '+repr(e)) from e
                    time.sleep(2**attempt)
        self.events.append({'kind':'embedding' if role=='embedding' else 'model','role':role,'call':key,'request_sha256':identity,'replayed':replayed,'artifact':str(response)})
        if role=='embedding':
            import math
            vector=data['data'][0]['embedding']
            if len(vector)!=1536 or not all(math.isfinite(float(x)) for x in vector):raise InfrastructureError('Expected finite 1536-dimensional embedding')
            return vector
        choice=data['choices'][0];raw=choice['message'].get('content') or ''
        if choice['finish_reason']!='stop':raise InvalidOutput('Non-complete generation: '+str(choice['finish_reason']))
        if not isinstance(raw,str) or not raw.strip():raise InvalidOutput('Empty response at '+key)
        return raw
    def tool(self,kind,inputs,run):
        self.tool_counter+=1
        if self.tool_counter>1024:raise InfrastructureError('Tool budget exceeded')
        d=self.output/'tools'/f'{self.tool_counter:04d}_{kind}';d.mkdir(parents=True,exist_ok=True)
        identity=sha(canonical(inputs));path=d/'checkpoint.json'
        if path.exists():
            cached=json.loads(path.read_text())
            if cached['input_sha256']!=identity or cached['result_sha256']!=sha(canonical(cached['result'])):raise InfrastructureError('Tool checkpoint changed')
            result=cached['result'];replayed=True
            self.counter+=cached.get('nested_model_calls',0)
            for role,n in cached.get('nested_role_counts',{}).items():self.role_counts[role]=self.role_counts.get(role,0)+n
        else:
            before=self.counter;roles_before=dict(self.role_counts)
            result=run(d/('execution_'+str(time.time_ns())));replayed=False
            delta={k:v-roles_before.get(k,0) for k,v in self.role_counts.items() if v!=roles_before.get(k,0)}
            write_json(path,{'input_sha256':identity,'result_sha256':sha(canonical(result)),'result':result,'nested_model_calls':self.counter-before,'nested_role_counts':delta})
        self.events.append({'kind':'tool','tool':kind,'artifact':str(path),'replayed':replayed})
        return result
