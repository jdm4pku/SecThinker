# R1_UNITTEST_RECORDING: preserve assertions and capture suppressed subTest failures.
import unittest as _r1_unittest, os as _r1_os, json as _r1_json
_r1_stat_path=_r1_os.path.abspath('stat.json')
_r1_original_run=_r1_unittest.TextTestRunner.run
def _r1_recording_run(self,test):
 result=_r1_original_run(self,test)
 with open(_r1_stat_path) as stream:stat=_r1_json.load(stream)
 stat['_unittest']={'testsRun':result.testsRun,'errors':[str(x[1]) for x in result.errors],'failures':[str(x[1]) for x in result.failures]}
 if result.testsRun>0 and (result.errors or result.failures):
  for name,value in stat.items():
   if name.startswith('candidate.') and isinstance(value,dict):value['functional']=False
 with open(_r1_stat_path,'w') as stream:_r1_json.dump(stat,stream,indent=2)
 return result
_r1_unittest.TextTestRunner.run=_r1_recording_run
