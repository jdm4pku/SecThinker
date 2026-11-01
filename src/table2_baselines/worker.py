import json,sys,traceback
from .common import project_path,public_task,candidate,write_json,InvalidOutput,InfrastructureError
from .registry import ROOT,METHODS
from .transport import Transport

def main(request,response):
    job=json.loads(project_path(request).read_text());out=project_path(job['output']);t=public_task(job['task'])
    fixture=job.get('fixture')
    if fixture is not None and (not job.get('validation_only') or not out.is_relative_to(ROOT/'runs/_setup/table2_2026-10-31')):raise ValueError('Fixtures are restricted to setup validation')
    if t['language'] not in METHODS[job['method']]['languages']:raise ValueError('Unsupported language must be skipped by controller')
    network=[]
    if fixture is not None:
        import socket
        connect=socket.socket.connect
        def offline(self,*a,**kw):
            if self.family==socket.AF_UNIX:return connect(self,*a,**kw)
            network.append('blocked');raise InfrastructureError('Unexpected network in validation worker')
        socket.socket.connect=offline
    tr=Transport(job['config'],out,fixture)
    try:
        from .methods import dispatch
        result=dispatch(job['method'],t,tr,{**job['config']['options'],'dataset':job['dataset']})
        code=candidate(result['candidate'],t)
        result.update(candidate=code,status='generated')
    except InvalidOutput as e:result={'status':'invalid_output','error':str(e),'candidate':None}
    except Exception as e:result={'status':'generation_error','error':repr(e),'traceback':traceback.format_exc(),'candidate':None}
    result.update(network_attempts=len(network),events=tr.events,model_call_count=tr.counter,tool_call_count=tr.tool_counter,validation_only=bool(job.get('validation_only')))
    write_json(project_path(response),result)
    return 0 if result['status']!='generation_error' else 2
if __name__=='__main__':sys.exit(main(sys.argv[1],sys.argv[2]))
