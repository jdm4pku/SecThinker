import errno,hashlib,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from prompt_baselines.core import ROOT,save,digest
from secthinker_experiments import artifacts as a,cli as batch
from secthinker_evaluation import sandbox,evaluate as ev

class OutputTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.root=Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def output(self,n=2):
  save(self.root/'experiment.json',{'dataset':'codeguard_plus','model':'test','prompt':'standard','sample_count':n})
  return self.root
 def test_layout_and_initial_result(self):
  with patch.object(a,'ROOT',self.root):
   p=a.create_output('codeguard_plus','Qwen/Qwen3-32B','secthinker_style',103)
   self.assertEqual(p.parent,self.root/'output/codeguard_plus')
   self.assertRegex(p.name,r'^Qwen-Qwen3-32B_secthinker_style_n103_\d{8}T\d{12}$')
   r=json.loads((p/'result.json').read_text())
   self.assertEqual(r['generation']['total'],103)
   self.assertIsNone(r['code_metrics']['Joint-Pass@1']['percent'])
 def test_missing_and_unknown_are_not_failures(self):
  p=self.output();d=p/'tasks/0000'
  save(d/'generation.json',{'status':'generated'})
  save(d/'evaluation.json',{'F':True,'S':None})
  (d/'completed_requirements.txt').write_text('requirements')
  r=a.write_result(p)
  self.assertEqual(r['requirements']['saved_samples'],1)
  self.assertIsNone(r['requirements']['SR-Recall'])
  self.assertIsNone(r['code_metrics']['F-Pass@1']['percent'])
  self.assertEqual(r['code_metrics']['F-Pass@1']['passed'],1)
  self.assertEqual(len(r['evaluation']['infrastructure_or_unknown_tasks']),1)
 def test_full_denominator_joint_and_independent_metrics(self):
  p=self.output()
  for i,r in enumerate([{'F':True,'S':False},{'F':False,'S':True}]):
   save(p/'tasks'/f'{i:04d}'/'generation.json',{'status':'generated'})
   save(p/'tasks'/f'{i:04d}'/'evaluation.json',r)
  r=a.write_result(p)
  self.assertEqual(r['status'],'complete')
  self.assertEqual(r['code_metrics']['F-Pass@1']['percent'],50)
  self.assertEqual(r['code_metrics']['Joint-Pass@1']['percent'],0)
  save(p/'tasks/0001/evaluation.json',{'F':False,'S':None})
  r=a.write_result(p)
  self.assertEqual(r['code_metrics']['F-Pass@1']['percent'],50)
  self.assertIsNone(r['code_metrics']['S-Pass@1']['percent'])
 def test_cleanup_transient_retry(self):
  parent=self.root/'clean';parent.mkdir();(parent/'child').mkdir()
  original=sandbox.shutil.rmtree
  calls=[]
  def remove(p):
   calls.append(p)
   if len(calls)==1:raise OSError(errno.ENOTEMPTY,'busy',str(p))
   original(p)
  with patch.object(sandbox.shutil,'rmtree',side_effect=remove),patch.object(sandbox.time,'sleep'):
   sandbox.clean_directory(parent,self.root/'logs')
  self.assertEqual(len(calls),2);self.assertEqual(list(parent.iterdir()),[])
  self.assertIn('traceback',json.loads((self.root/'logs/cleanup_retries.json').read_text())[0])
 def test_persistent_cleanup_stops_before_execution(self):
  for name in ['tmp/child','var/tmp','work']:(self.root/name).mkdir(parents=True)
  with patch.object(sandbox,'ROOT',self.root),patch.object(sandbox,'ROOTFS',self.root),patch.object(sandbox.shutil,'rmtree',side_effect=OSError(errno.ENOTEMPTY,'busy')) as rm,patch.object(sandbox.time,'sleep'),patch.object(sandbox.subprocess,'Popen') as execute:
   with self.assertRaises(OSError):sandbox.run_sandbox({},['no'],self.root/'logs')
   self.assertEqual(rm.call_count,5);execute.assert_not_called()
 def test_permission_cleanup_is_not_retried(self):
  parent=self.root/'clean';(parent/'child').mkdir(parents=True)
  with patch.object(sandbox.shutil,'rmtree',side_effect=PermissionError(errno.EACCES,'denied')) as rm:
   with self.assertRaises(PermissionError):sandbox.clean_directory(parent,self.root/'logs')
   self.assertEqual(rm.call_count,1)
 def test_partial_evaluation_preserves_functional_result(self):
  p=self.output(1);code='def f(): return 1\n';key='SecEvalBase/test';d=p/'tasks/0000'
  save(p/'manifest.json',{'config':{'dataset':'codesec_eval','model':'test','method':'standard'},'task_count':1,'created_at':'test'})
  save(d/'generation.json',{'status':'generated','candidate':'candidate.py','candidate_sha256':digest(code)})
  (d/'candidate.py').write_text(code)
  save(d/'evaluation.json',{'key':key,'F':True,'S':None,'candidate_sha256':digest(code),'test_F':{'sentinel':'keep'},'error_S':'old'})
  with patch.object(ev,'tasks',return_value=[{'index':0,'key':key}]),patch.object(ev,'cse_rows',return_value={key:{'Entry_Point':'f','Test-FP':'F','Test-SP':'S'}}),patch.object(ev,'codesec_test',return_value={'passed':True}) as run,patch.object(ev,'audit_runtime',return_value={'changed':[]}):
   ev.evaluate(p)
   self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[2],'S')
  r=json.loads((d/'evaluation.json').read_text());self.assertEqual(r['test_F'],{'sentinel':'keep'});self.assertNotIn('error_S',r)
 def test_batch_evaluation_continues_after_failure(self):
  groups=[]
  for i in range(2):
   out=self.root/'output/codeguard_plus'/str(i);out.mkdir(parents=True);(out/'generation.done').touch()
   save(out/'experiment.json',{'dataset':'codeguard_plus','model':'test','prompt':'standard','sample_count':1})
   groups.append({'dataset':'codeguard_plus','method':'standard','output':str(out),'limit':1})
  path=self.root/'output/batches/test.json';save(path,{'model':'test','endpoint':'unused','groups':groups})
  with patch.object(batch,'ROOT',self.root),patch.object(batch.subprocess,'call',side_effect=[1,0]) as run:
   self.assertEqual(batch.run(path,'evaluate'),1);self.assertEqual(run.call_count,2)
 def test_upgrade_requires_flag_preserves_completed_results(self):
  from secthinker_evaluation import runner
  p=self.output(1)
  save(p/'manifest.json',{'config':{'dataset':'codeguard_plus','model':'test','method':'standard'},'task_count':1,'created_at':'test'})
  save(p/'tasks/0000/generation.json',{'status':'generated'})
  sentinel={'F':True,'S':True,'sentinel':'keep'}
  save(p/'tasks/0000/evaluation.json',sentinel)
  ledger=json.loads((ROOT/'src/secthinker_evaluation/runtime_upgrade.json').read_text())
  cfg={'source_sha256':ledger['from_sources'],'generation_manifest_sha256':hashlib.sha256((p/'manifest.json').read_bytes()).hexdigest(),'code_metrics':['F-Pass@1','S-Pass@1','Pass@1'],'Pass@1_definition':'functional AND security','requirements_metrics':'not computed; no ground truth','runtime_manifest_sha256':hashlib.sha256((ROOT/'runs/_setup/prompt_baselines/rootfs_static_manifest.json').read_bytes()).hexdigest()}
  old={'config':cfg,'created_at':'before'};save(p/'evaluation_manifest.json',old)
  with patch.object(runner,'evaluate') as run:
   with self.assertRaisesRegex(RuntimeError,'Evaluator changed'):runner.main(p)
   run.assert_not_called()
  save(p/'metrics.json',{'status':'complete','N':1})
  with patch.object(runner,'evaluate') as run:
   runner.main(p,True);run.assert_called_once()
  self.assertEqual(json.loads((p/'provenance/evaluation_manifest.before_runtime_v2.json').read_text()),old)
  self.assertEqual(json.loads((p/'tasks/0000/evaluation.json').read_text()),sentinel)
  self.assertEqual(json.loads((p/'result.json').read_text())['status'],'complete')
 def test_runtime_upgrade_ledger_matches_live_files(self):
  ledger=json.loads((ROOT/'src/secthinker_evaluation/runtime_upgrade.json').read_text())
  for p,h in ledger['to_sources'].items():self.assertEqual(hashlib.sha256((ROOT/p).read_bytes()).hexdigest(),h,p)

if __name__=='__main__':unittest.main(verbosity=2)
