import json,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from memory_validation import run
class RunnerTests(unittest.TestCase):
    def test_timeout_is_fail(self):
        with patch.object(run.subprocess,'run',side_effect=subprocess.TimeoutExpired('safe',100)):
            self.assertEqual(run.run_phase('unit','unused')['code'],'worker_timeout')
    def test_missing_report_is_fail(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            self.assertEqual(run.run_phase('unit',tmp)['status'],'FAIL')
    def test_missing_endpoint_cannot_pass(self):
        with patch.dict(run.os.environ,{},clear=True),patch.object(run,'run_phase',return_value={'status':'PASS'}):
            value=run.validate()
        self.assertEqual(value['overall'],'FAIL')
        self.assertEqual([x['code'] for x in value['checks'][3:]],['live_endpoint_not_used']*5)
    def test_malformed_report_is_fail(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            (Path(tmp)/'unit.json').write_text('{bad')
            self.assertEqual(run.run_phase('unit',tmp)['status'],'FAIL')
    def test_endpoint_not_passed_to_offline_worker(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(run.os.environ,{'SOLANA_RPC_URL':'https://example.invalid/secret'}),patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as proc:
            run.run_phase('offline_replay',tmp,block=True)
            self.assertNotIn('SOLANA_RPC_URL',proc.call_args.kwargs['env'])
