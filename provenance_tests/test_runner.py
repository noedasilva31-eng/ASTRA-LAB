import os,subprocess,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from provenance_validation import run
class RunnerTests(unittest.TestCase):
    def test_missing_endpoint_never_passes(self):
        with patch.dict(os.environ,{},clear=True),patch.object(run,'run_phase',return_value={'status':'PASS'}):r=run.validate()
        self.assertEqual(r['overall'],'FAIL');self.assertEqual([x['code'] for x in r['checks'][3:]],['live_endpoint_not_used']*5)
    def test_timeout_fails(self):
        with patch.object(run.subprocess,'run',side_effect=subprocess.TimeoutExpired('safe',150)):
            self.assertEqual(run.run_phase('unit','unused')['code'],'worker_timeout')
    def test_missing_report_fails(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],0)):
            self.assertEqual(run.run_phase('unit',tmp)['status'],'FAIL')
    def test_offline_worker_does_not_receive_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'SOLANA_RPC_URL':'https://example.invalid/secret'}),patch.object(run.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as proc:
            run.run_phase('live_provenance',tmp);self.assertNotIn('SOLANA_RPC_URL',proc.call_args.kwargs['env'])
