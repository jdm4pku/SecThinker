import json, os, signal, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from prompt_baselines.core import ROOT, save
from secthinker_baselines.cli import request, output_lock, generate_one, generate
from secthinker_baselines.tests.test_protocol import ProtocolTests, TASK, CONTENT

class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.out=Path(self.tmp.name)
        self.args=ProtocolTests().args(self.out)
    def tearDown(self):self.tmp.cleanup()
    def test_received_response_is_reused_without_network(self):
        d=self.out/'tasks/0000';d.mkdir(parents=True)
        save(d/'code.response.2.json',{'response':{'choices':[{'message':{'content':CONTENT},'finish_reason':'stop'}],'usage':{}}})
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('must not regenerate')):
            self.assertEqual(generate_one(TASK,self.args),'generated')
        self.assertEqual((d/'raw_content.txt').read_text(),CONTENT)
    def test_infrastructure_error_is_retryable_but_model_failure_is_not(self):
        with patch('secthinker_baselines.cli.request',side_effect=ConnectionError('offline')):
            self.assertEqual(generate_one(TASK,self.args),'generation_error')
        with patch('secthinker_baselines.cli.request',return_value=(CONTENT,'length',{})) as mock:
            self.assertEqual(generate_one(TASK,self.args),'invalid_output')
            self.assertEqual(generate_one(TASK,self.args),'invalid_output')
            self.assertEqual(mock.call_count,1)
        self.assertTrue(list((self.out/'tasks/0000/infrastructure_history').glob('*.json')))
    def test_lock_recovers_after_sigkill_and_rejects_concurrent_writer(self):
        script='from pathlib import Path\nfrom secthinker_baselines.cli import output_lock\nimport time\nwith output_lock(Path('+repr(str(self.out))+')):\n print("locked",flush=True)\n time.sleep(60)\n'
        p=subprocess.Popen([sys.executable,'-B','-c',script],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(),'locked')
            with self.assertRaises(RuntimeError):
                with output_lock(self.out):pass
            p.kill();p.wait()
            with output_lock(self.out):pass
        finally:
            if p.poll() is None:p.kill();p.wait()
            p.stdout.close()
    def test_service_failure_stops_queued_requests(self):
        tasks=[{**TASK,'index':i,'key':str(i)} for i in range(10)]
        with patch('secthinker_baselines.cli.request',side_effect=ConnectionError('offline')) as mock:
            with self.assertRaises(RuntimeError):generate(self.args,tasks)
            self.assertEqual(mock.call_count,1)
        self.assertEqual(json.loads((self.out/'status.json').read_text())['phase'],'paused_infrastructure')
if __name__=='__main__':unittest.main(verbosity=2)
