import json,tempfile,unittest
from pathlib import Path
from prompt_baselines.core import ROOT,tasks,code_prompt,hint_prompt,extract,aggregate,save
from prompt_baselines.codeguard import resolve_query
class EvaluationContracts(unittest.TestCase):
 def test_dataset_sizes(self):
  self.assertEqual(len(tasks('codesec_eval')),255);self.assertEqual(len(tasks('codeguard_plus')),103)
 def test_no_evaluation_fields_in_prompt(self):
  t={'language':'py','problem':'def f(x): pass','entry_point':'f','key':'SECRET_LABEL','Test-SP':'SECRET_TEST','Secure Code':'SECRET_REFERENCE'}
  prompt=code_prompt(t)+hint_prompt(t)
  for value in ['SECRET_LABEL','SECRET_TEST','SECRET_REFERENCE']:self.assertNotIn(value,prompt)
 def test_exact_prefix_and_indentation(self):
  t={'language':'py','prefix':'def f(x):\n    # finish'}
  self.assertEqual(extract('```python\n    return x\n```',t),t['prefix']+'\n    return x\n')
 def test_multiple_code_blocks_rejected(self):
  with self.assertRaises(ValueError):extract('```py\nx\n```\n```py\ny\n```',{'language':'py'})
 def test_independent_S_joint_and_failure_denominator(self):
  with tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='metric-contract-') as d:
   d=Path(d);save(d/'manifest.json',{'task_count':4})
   for i,(f,s) in enumerate([(True,False),(False,True),(True,True),(False,False)]):save(d/'tasks'/f'{i:04d}'/'evaluation.json',{'F':f,'S':s})
   self.assertEqual(aggregate(d)['metrics'],{'F-Pass@1':.5,'S-Pass@1':.5,'Joint-Pass@1':.25})
   save(d/'tasks/0003/evaluation.json',{'F':False,'S':None})
   result=aggregate(d);self.assertEqual(result['N'],4);self.assertEqual(result['status'],'incomplete');self.assertIsNone(result['metrics']['S-Pass@1'])
 def test_every_codeguard_task_has_security_criterion(self):
  q=sonar_only=0
  for t in tasks('codeguard_plus'):
   path=resolve_query(t);sonar=t['language']=='py' and t['key']!='cwe-327/2-py'
   self.assertTrue(path is not None or sonar)
   if path:self.assertTrue(path.exists());q+=1
   else:sonar_only+=1
  self.assertEqual(q,94);self.assertEqual(sonar_only,9)
if __name__=='__main__':unittest.main(verbosity=2)
