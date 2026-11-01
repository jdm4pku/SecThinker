import hashlib,json,traceback
from pathlib import Path
from .core import ROOT,tasks,save,now,aggregate
from .sandbox import codesec_test,audit_runtime

def cse_rows():
 rows={}
 for subset in ['SecEvalBase','SecEvalPlus']:
  for line in (ROOT/'data/CodeSecEval/data'/subset/'test.jsonl').read_text().splitlines():
   row=json.loads(line);rows[subset+'/'+str(row['ID'])]=row
 return rows

def evaluate(output):
 manifest=json.loads((output/'manifest.json').read_text());dataset=manifest['config']['dataset'];ts=tasks(dataset)
 if manifest['task_count']!=len(ts):ts=ts[:manifest['task_count']]
 rows=cse_rows() if dataset=='codesec_eval' else None
 if dataset=='codeguard_plus':
  from .codeguard import evaluate_codeguard
  return evaluate_codeguard(output,ts)
 for i,t in enumerate(ts):
  d=output/'tasks'/f'{i:04d}';p=d/'evaluation.json'
  if p.exists():continue
  g=json.loads((d/'generation.json').read_text());r={'index':i,'key':t['key'],'candidate_sha256':g.get('candidate_sha256'),'F':None,'S':None,'evaluator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
  if g['status']=='invalid_output':r.update(F=False,S=False,error=g.get('error'),failure_kind='invalid_model_output')
  elif g['status']=='generation_error':r.update(error=g.get('error'),failure_kind='generation_infrastructure')
  else:
   code=(d/g['candidate']).read_text()
   assert hashlib.sha256(code.encode()).hexdigest()==g['candidate_sha256']
   row=rows[t['key']]
   for field,k in [('Test-FP','F'),('Test-SP','S')]:
    try:
     result=codesec_test(code,row['Entry_Point'],row[field],d/('test_'+k));r[k]=result['passed'];r['test_'+k]=result
    except Exception as e:r['error_'+k]=repr(e)
  r['Joint']=r['F'] and r['S'] if r['F'] is not None and r['S'] is not None else None
  save(p,r);save(output/'status.json',{'phase':'evaluation','completed':i+1,'total':len(ts),'updated_at':now()});print(f'{now()} evaluated {i+1}/{len(ts)} F={r["F"]} S={r["S"]}',flush=True)
 save(output/'runtime_integrity.json',audit_runtime())
 result=aggregate(output);save(output/'status.json',{'phase':result['status'],'metrics':result,'updated_at':now()});print(json.dumps(result,indent=2),flush=True)
