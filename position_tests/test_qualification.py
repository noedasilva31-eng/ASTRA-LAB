import unittest
from astra_position.__main__ import qualification
class QualificationTests(unittest.TestCase):
    def test_inherited_position_is_not_new_live_evidence(self):
        self.assertEqual(qualification(0,{'state':'OPEN_POSITION'},[])['status'],'NOT_EXECUTED')
    def test_source_failure_is_not_missing_prerequisite(self):
        self.assertEqual(qualification(0,{},['rpc_transport_failure'])['status'],'FAIL')
    def test_fresh_hold_can_qualify_without_sell(self):
        r=qualification(1,{'state':'OPEN_POSITION'},['quota_exhausted']);self.assertEqual(r['status'],'PASS');self.assertEqual(r['session']['state'],'OPEN_POSITION')
