import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from validate_all_current import flatten
import observer_validation
class ObserverGateTests(unittest.TestCase):
    def test_missing_prerequisite_not_report_inconsistency(self):
        rows=flatten('Observer',{'overall':'FAIL','checks':[{'id':'live','status':'NOT_EXECUTED','code':'observer_mainnet_configuration_missing'}]})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'NOT_EXECUTED')
    def test_real_failure_is_preserved(self):
        rows=flatten('Observer',{'overall':'FAIL','checks':[{'id':'live','status':'FAIL','code':'genesis_mismatch'}]});self.assertEqual(rows[0]['code'],'genesis_mismatch');self.assertEqual(rows[0]['status'],'FAIL')
    def test_self_test_never_calls_configured_provider(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'ASTRA_OBSERVER_NETWORK':'mainnet','ASTRA_OBSERVER_RPC_URL':'https://fixture.invalid'}),patch('sys.argv',['observer_validation.py','--self-test']),patch.object(observer_validation,'search',side_effect=AssertionError('network forbidden')):
            p=Path(tmp)/'report.json';self.assertEqual(observer_validation.main(p),1);report=json.loads(p.read_text());self.assertTrue(all(x['status']=='NOT_EXECUTED' for x in report['checks']))
