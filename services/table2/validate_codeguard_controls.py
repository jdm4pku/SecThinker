"""Synthetic Python/C/C++ controls through the actual CodeGuard functional bridge."""
import json,tempfile,time
from pathlib import Path
from unittest.mock import patch
from table2_baselines.common import ROOT,write_json
from table2_baselines.evaluate import functional
from secthinker_evaluation import codeguard
SETUP=ROOT/'runs/_setup/table2_2026-10-31'
work=Path(tempfile.mkdtemp(prefix='codeguard-controls-',dir=SETUP));bench=work/'benchmark'
(bench/'unit_test').mkdir(parents=True)
(bench/'unit_test/test_utils.py').write_text('def compile_c_file(*a,**kw): raise AssertionError("Expected the existing checked compiler bridge")\n')
results=[]
for language in ['py','c','cpp']:
    key='fixture/0-'+language;directory=bench/'unit_test'/key;directory.mkdir(parents=True)
    script='''import json,traceback
from pathlib import Path
from test_utils import compile_c_file
import subprocess
lang="'''+language+'''"
passed=False
try:
 code=Path('candidates/candidate.'+lang).read_text()
 if lang=='py':
  ns={};exec(compile(code,'candidate.py','exec'),ns)
  assert ns['add'](2,3)==5
 else:
  path=Path('control.'+lang)
  path.write_text(code+'\\nint main(void) { return add(2,3)==5 ? 0 : 1; }\\n')
  compile_c_file(str(path))
  assert subprocess.run(['./a.out']).returncode==0
 passed=True
except BaseException:
 traceback.print_exc()
stat=json.load(open('stat.json'));stat['candidate.'+lang]['functional']=passed
json.dump(stat,open('stat.json','w'))
'''
    (directory/'functional.py').write_text(script)
    for good in [True,False]:
        operator='+' if good else '-'
        code=f'def add(a,b):\n    return a {operator} b\n' if language=='py' else f'int add(int a,int b) {{ return a {operator} b; }}\n'
        output=work/(language+('_positive' if good else '_negative'))
        with patch.object(codeguard,'BENCH',bench):report=functional({'key':key,'language':language,'index':0},code,output)
        assert report['passed'] is good,(language,good,report)
        cleanup=json.loads((output/'jail_cleanup.json').read_text());assert cleanup['removed']
        results.append({'language':language,'expected':good,'passed':report['passed'],'output':str(output),'runtime_clone':report['execution']['runtime_clone']})
        print(language,'positive' if good else 'negative','OK',flush=True)
report={'passed':True,'controls':results,'work_directory':str(work),'formal_benchmark_tasks':0,'real_model_calls':0,'assertion_source':'Synthetic add/subtract controls through unchanged CodeGuard functional harness and private jail'}
write_json(SETUP/'codeguard-controls.json',report);print(json.dumps(report,indent=2))
