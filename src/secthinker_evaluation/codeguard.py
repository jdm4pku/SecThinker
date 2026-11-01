"""CodeGuard+ adapters: original assertions and task queries, independent F/S."""
import traceback
from secthinker_experiments.artifacts import write_result
import concurrent.futures,csv,hashlib,json,os,re,shlex,shutil,subprocess,time,urllib.request,urllib.parse
from pathlib import Path
from .core import ROOT,save,now,aggregate
from .sandbox import run_sandbox,audit_runtime
BENCH=ROOT/'data/CodeGuardPlus'
TOOLS=ROOT/'tools/prompt_eval'

def tool_env(work):
 work=Path(work)
 for n in ['tmp','home','cache']:(work/n).mkdir(parents=True,exist_ok=True)
 return {**os.environ,'TMPDIR':str(work/'tmp'),'TMP':str(work/'tmp'),'TEMP':str(work/'tmp'),'XDG_CACHE_HOME':str(work/'cache'),'PYTHONDONTWRITEBYTECODE':'1','JAVA_TOOL_OPTIONS':'-Djava.io.tmpdir='+str(work/'tmp')+' -Duser.home='+str(work/'home')+' -XX:-UsePerfData','CODEQL_RAM':'4096','LD_PRELOAD':str(ROOT/'tools/prompt_eval/libefs_lock_compat.so'),'XDG_CONFIG_HOME':str(work/'home/config')}
def tool_run(argv,work,name,timeout=1200,env=None):
 work=Path(work);work.mkdir(parents=True,exist_ok=True)
 with open(work/(name+'.stdout'),'w') as out,open(work/(name+'.stderr'),'w') as err:
  p=subprocess.run([str(a) for a in argv],stdout=out,stderr=err,cwd=work,env=env or tool_env(work),timeout=timeout)
 save(work/(name+'.status.json'),{'argv':[str(a) for a in argv],'returncode':p.returncode,'finished_at':now()})
 if p.returncode:raise RuntimeError(name+' failed; see '+str(work/(name+'.stderr')))

def sonar_api(path,params=None,post=False):
 token=json.loads((Path(os.environ.get('R1_SONAR_CREDENTIALS',str(ROOT/'runtime/sonarqube/server4/credentials.json')))).read_text())['token']
 url='http://127.0.0.1:19000/api/'+path;data=urllib.parse.urlencode(params or {})
 req=urllib.request.Request(url+('' if post else '?'+data),data=data.encode() if post else None,headers={'Authorization':'Bearer '+token})
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=60) as response:
  body=response.read();return json.loads(body) if body else {}

def sonar_scan(output,ts):
 work=output/'security/sonar';work.mkdir(parents=True,exist_ok=True);resultfile=work/'results.json'
 if resultfile.exists():return json.loads(resultfile.read_text())
 src=work/'sources';src.mkdir(exist_ok=True);expected={}
 for t in ts:
  if t['language']!='py' or t['key']=='cwe-327/2-py':continue
  d=output/'tasks'/f'{t["index"]:04d}';g=json.loads((d/'generation.json').read_text())
  if g['status']!='generated':continue
  filename=f't{t["index"]:04d}.py';shutil.copyfile(d/g['candidate'],src/filename);expected[filename]=t['key']
 if not expected:save(resultfile,{});return {}
 project='r1-'+hashlib.sha256(str(output).encode()).hexdigest()[:20]
 try:sonar_api('projects/create',{'project':project,'name':output.name,'visibility':'private'},True)
 except urllib.error.HTTPError as e:
  if e.code!=400:raise
 # Preserve the exact server/plugin/profile state used by both methods.
 save(work/'server.json',sonar_api('system/status'))
 save(work/'plugins.json',sonar_api('plugins/installed'))
 save(work/'profiles.json',sonar_api('qualityprofiles/search',{'language':'py'}))
 token=json.loads((Path(os.environ.get('R1_SONAR_CREDENTIALS',str(ROOT/'runtime/sonarqube/server4/credentials.json')))).read_text())['token']
 props={'sonar.projectKey':project,'sonar.projectBaseDir':str(work),'sonar.sources':'sources','sonar.host.url':'http://127.0.0.1:19000','sonar.scm.disabled':'true','sonar.python.version':'3.10','sonar.sourceEncoding':'UTF-8','sonar.working.directory':str(work/'scannerwork'),'sonar.token':token}
 propfile=work/'sonar-project.properties';propfile.write_text('\n'.join(k+'='+v for k,v in props.items())+'\n')
 java=next(TOOLS.glob('zulu21*-jdk*/bin/java'));scanner=TOOLS/'sonar-scanner-5.0.1.3006-linux';jar=next((scanner/'lib').glob('*.jar'))
 env=tool_env(work);env['SONAR_USER_HOME']=str(work/'home');env['JAVA_HOME']=str(java.parent.parent)
 try:
  tool_run([java,'-Xmx2g','-cp',jar,'org.sonarsource.scanner.cli.Main','-Dproject.settings='+str(propfile)],work,'scan',env=env)
 finally:
  props.pop('sonar.token');propfile.write_text('\n'.join(k+'='+v for k,v in props.items())+'\n')
 report=dict(line.split('=',1) for line in (work/'scannerwork/report-task.txt').read_text().splitlines() if '=' in line)
 for _ in range(300):
  ce=sonar_api('ce/task',{'id':report['ceTaskId']});save(work/'ce_task.json',ce);status=ce['task']['status']
  if status=='SUCCESS':break
  if status in ('FAILED','CANCELED'):raise RuntimeError('Sonar analysis '+status)
  time.sleep(2)
 else:raise TimeoutError('Sonar compute engine did not complete')
 tree=sonar_api('measures/component_tree',{'component':project,'metricKeys':'security_issues','qualifiers':'FIL','ps':500,'p':1});save(work/'measures.json',tree)
 if tree['paging']['total']>500:raise RuntimeError('Unexpected scan size')
 results={}
 for component in tree['components']:
  filename=Path(component['path']).name
  if filename not in expected:continue
  values=[m['value'] for m in component.get('measures',[]) if m['metric']=='security_issues']
  if len(values)!=1:raise RuntimeError('Missing security_issues metric for '+filename)
  counts=json.loads(values[0]);assert isinstance(counts,dict)
  results[expected[filename]]={'passed':not any(v>0 for v in counts.values()),'counts':counts,'component':component['key'],'analysis_id':ce['task'].get('analysisId')}
 if set(results)!=set(expected.values()):raise RuntimeError('Sonar file coverage incomplete')
 log=(work/'scan.stdout').read_text(errors='replace')+(work/'scan.stderr').read_text(errors='replace')
 if re.search(r'Unable to parse|Failed to parse|ERROR',log):raise RuntimeError('Sonar reported analysis errors; inspect scanner logs')
 save(resultfile,results);return results

FUNCTIONAL_RUNNER=r"""import os,sys,runpy,subprocess,json
sys.path.insert(0,os.path.abspath('unit_test'))
import test_utils
# Preserve all assertions. Check compiler exit status and create an executable
# inode with executable mode, required by this EFS mount's chmod behavior.
def compile_checked(filename,cc='gcc',cc_args=None,additonal_args=None):
 if filename.endswith('.cpp'):cc='g++';cc_args=['-std=c++11','-o','a.out']
 elif cc_args is None:cc_args=['-std=c99','-o','a.out']
 if os.path.exists('a.out'):os.unlink('a.out')
 p=subprocess.run([cc]+cc_args+[filename]+(additonal_args or []),capture_output=True)
 if p.returncode:raise RuntimeError('compile failed: '+p.stderr.decode(errors='replace'))
 data=open('a.out','rb').read();os.unlink('a.out')
 with os.fdopen(os.open('a.out',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o755),'wb') as f:f.write(data)
test_utils.compile_c_file=compile_checked
script=sys.argv[1];sys.argv=[script,'--path',os.path.abspath('candidates')]
runpy.run_path(script,run_name='__main__')
"""
def functional(t,code,output):
 key=t['key'];lang=t['language'];stat={'candidate.'+lang:{'num':1}}
 files={'candidates/candidate.'+lang:code,'stat.json':json.dumps(stat),'unit_test/test_utils.py':BENCH/'unit_test/test_utils.py','runner.py':FUNCTIONAL_RUNNER}
 for p in (BENCH/'unit_test'/key).iterdir():
  if p.is_file():files['unit_test/'+key+'/'+p.name]=p
 # The original sales helper has a fixed ~/CodeGuardPlus path; provision it inside the jail.
 result=run_sandbox(files,['/usr/bin/python3','-B','runner.py','unit_test/'+key+'/functional.py'],output,timeout=45,collect=['stat.json'],allow_server=(key=='cwe-215/0-py'))
 stat=json.loads(result['collected'].get('stat.json','{}'));flag=stat.get('candidate.'+lang,{}).get('functional')
 stderr=(Path(output)/'stderr.txt').read_text(errors='replace')
 if flag is None:
  if result['timeout']:return {'passed':False,'error':'functional_timeout','execution':result}
  return {'passed':None,'error':'test_did_not_record_result','stderr':stderr,'execution':result}
 return {'passed':bool(flag),'execution':result}

def resolve_query(t):
 info=json.loads((BENCH/'data/base'/t['key']/'info.json').read_text());query=info['check_ql']
 if not query:return None
 language='python' if t['language']=='py' else 'cpp';bundle=TOOLS/'codeql';pack=next((bundle/'qlpacks/codeql'/f'{language}-queries').iterdir())
 if t['key']=='cwe-190/1-c':return ROOT/'tools/prompt_eval/custom_queries/cpp/ArithmeticTainted.ql'
 if '/ql/src/' in query:return pack/query.split('/ql/src/',1)[1].replace('\\ ', ' ')
 return ROOT/'tools/prompt_eval/custom_queries'/language/t['key']/Path(query).name

def codeql(t,code,output):
 work=Path(output);work.mkdir(parents=True,exist_ok=True);cached=work/'result.json'
 if cached.exists():return json.loads(cached.read_text())
 query=resolve_query(t)
 if query is None:return {'applicable':False}
 assert query.exists(),str(query)
 src=work/'source';src.mkdir(exist_ok=True);filename='candidate.'+t['language'];(src/filename).write_text(code)
 cli=TOOLS/'codeql/codeql';env=tool_env(work);env['CODEQL_EXTRACTOR_PYTHON_DISABLE_LIBRARY_EXTRACTION']='true'
 args=[cli,'database','create',work/'database','--source-root',src,'--language','python' if t['language']=='py' else 'cpp','--threads=2']
 if t['language'] in ['c','cpp']:
  compiler='g++' if t['language']=='cpp' else 'gcc';std='c++11' if t['language']=='cpp' else 'c99'
  # Compile only; never execute a generated binary outside the execution jail.
  compile_cmd=[compiler,'-std='+std,'-c',str(src/filename),'-o',str(src/'candidate.o')]
  with open(work/'compile.stdout','w') as out,open(work/'compile.stderr','w') as err:p=subprocess.run(compile_cmd,cwd=src,stdout=out,stderr=err,env=env,timeout=30)
  if p.returncode:
   result={'applicable':True,'passed':False,'invalid_code':True,'error':'candidate_compile_failure'};save(cached,result);return result
  args+=['--command='+shlex.join(compile_cmd)]
 if not ((work/'database/codeql-database.yml').exists() and (work/'database/src.zip').exists()):
  if (work/'database').exists():
   incomplete=work/('database.interrupted.'+str(time.time_ns()));(work/'database').rename(incomplete)
  tool_run(args,work,'database_create',env=env)
 # Fail closed if a DB was built without the candidate file.
 archives=list((work/'database').glob('src.zip'))
 if not archives:raise RuntimeError('Missing CodeQL source archive')
 import zipfile
 with zipfile.ZipFile(archives[0]) as z:
  if not any(x.endswith('/'+filename) for x in z.namelist()):raise RuntimeError('Candidate absent from CodeQL extraction')
 csvpath=work/'findings.csv'
 tool_run([cli,'database','analyze',work/'database',query,'--format=csv','--output='+str(csvpath),'--threads=2','--ram=4096'],work,'analyze',env=env)
 findings=[]
 with csvpath.open() as f:
  for row in csv.reader(f):
   if len(row)<9:raise RuntimeError('Malformed CodeQL finding')
   if Path(row[-5]).name==filename:findings.append(row)
 ignored=[]
 if t['key'].startswith('cwe-078/') and t['language']=='py' and findings:
  import sys
  sys.path.insert(0,str(ROOT/'envs/benchmark-rootfs/opt/site-packages'))
  import libcst as cst
  from libcst.metadata import PositionProvider
  from libcst._position import CodePosition
  import ast
  original=(BENCH/'codeql_eval.py').read_text();tree=ast.parse(original);node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CWE78Visitor');ns={'cst':cst,'PositionProvider':PositionProvider}
  exec(ast.get_source_segment(original,node),ns);kept=[]
  for row in findings:
   visitor=ns['CWE78Visitor'](code,CodePosition(int(row[-4]),int(row[-3])-1),CodePosition(int(row[-2]),int(row[-1])))
   cst.MetadataWrapper(cst.parse_module(code)).visit(visitor)
   (ignored if visitor.fp else kept).append(row)
  findings=kept
 result={'applicable':True,'passed':not findings,'query':str(query),'query_sha256':hashlib.sha256(query.read_bytes() if query.is_file() else b''.join(p.read_bytes() for p in sorted(query.rglob('*.ql')))).hexdigest(),'findings':findings,'ignored_official_cwe78_filter':ignored,'version':'2.17.5'};save(cached,result);return result

def evaluate_codeguard(output,ts):
 save(output/'status.json',{'phase':'sonar_scan','total':len(ts),'updated_at':now()})
 try:sonar=sonar_scan(output,ts);sonar_error=None
 except Exception as e:sonar={};sonar_error=repr(e);save(output/'security/sonar/error.json',{'error':sonar_error})
 def one(t):
  i=t['index'];d=output/'tasks'/f'{i:04d}';g=json.loads((d/'generation.json').read_text());p=d/'evaluation.json'
  previous={}
  if p.exists():
   previous=json.loads(p.read_text())
   if previous.get('F') is not None and previous.get('S') is not None:return previous
  r={'index':i,'key':t['key'],'candidate_sha256':g.get('candidate_sha256'),'F':None,'S':None}
  if previous:
   if previous.get('candidate_sha256')!=g.get('candidate_sha256'):raise RuntimeError('Candidate changed since evaluation')
   r.update(previous)
  if g['status']=='invalid_output':r.update(F=False,S=False,error=g.get('error'),failure_kind='invalid_model_output')
  elif g['status']=='generation_error':r.update(error=g.get('error'),failure_kind='generation_infrastructure')
  else:
   code=(d/g['candidate']).read_text();assert hashlib.sha256(code.encode()).hexdigest()==g['candidate_sha256']
   if r.get('F') is None:
    try:r['functional']=functional(t,code,d/'functional');r['F']=r['functional']['passed'];r.pop('functional_error',None)
    except Exception as e:r['functional_error']=repr(e);r['functional_traceback']=traceback.format_exc()
   checks=[]
   try:
    q=codeql(t,code,d/'codeql');r['codeql']=q
    if q.get('applicable'):checks.append(q.get('passed'))
   except Exception as e:r['codeql_error']=repr(e);r['codeql_traceback']=traceback.format_exc();checks.append(None)
   if t['language']=='py' and t['key']!='cwe-327/2-py':
    r['sonar']=sonar.get(t['key'],{'passed':None,'error':sonar_error or 'file_not_scanned'});checks.append(r['sonar']['passed'])
   if checks and all(x is not None for x in checks):r['S']=all(checks)
   if r.get('codeql',{}).get('invalid_code'):r.update(F=False,S=False)
  r['Joint']=r['F'] and r['S'] if r['F'] is not None and r['S'] is not None else None;save(p,r);return r
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for i,f in enumerate(concurrent.futures.as_completed([pool.submit(one,t) for t in ts]),1):
   r=f.result();write_result(output);save(output/'status.json',{'phase':'evaluation','completed':i,'total':len(ts),'updated_at':now()});print(f'{now()} evaluated {i}/{len(ts)} {r["key"]} F={r["F"]} S={r["S"]}',flush=True)
 save(output/'runtime_integrity.json',audit_runtime())
 result=aggregate(output);save(output/'status.json',{'phase':result['status'],'metrics':result,'updated_at':now()});print(json.dumps(result,indent=2),flush=True)
