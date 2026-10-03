import copy,tempfile,unittest
from pathlib import Path
from astra_observer.spine import Archive,NETWORKS,decode_frame
from astra_observer.engine import Engine,replay
from observer_tests.test_observer import transaction,response
class RoutedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=Archive(self.root/'a','mainnet');self.g=self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash'})
    def tearDown(self):self.a.close();self.tmp.cleanup()
    def tx(self):
        t=transaction();parent=copy.deepcopy(t['transaction']['message']['instructions'][0]);parent['stackHeight']=2;emit=t['meta']['innerInstructions'][0]['instructions'][0];emit['stackHeight']=3;t['transaction']['message']['instructions']=[dict(parent,programIdIndex=0)];t['meta']['innerInstructions'][0]['instructions']=[parent,emit];return t
    def decode(self,t):
        seq=self.a.append('rpc',response(t),{'method':'getTransaction','params':[t['transaction']['signatures'][0],{'commitment':'confirmed'}]});return decode_frame(self.a,seq,self.g)
    def test_routed_swap_uses_nearest_authenticated_parent(self):
        r=self.decode(self.tx());self.assertEqual(len(r['events']),1);e=r['events'][0];self.assertEqual(e['parent_inner_index'],0);self.assertEqual(e['inner_instruction_index'],1);self.assertEqual(e['call_depth'],2)
    def test_missing_parent_depth_unresolved(self):
        t=self.tx();t['meta']['innerInstructions'][0]['instructions'][0]['stackHeight']=None;r=self.decode(t);self.assertFalse(r['events']);self.assertTrue(any(s.get('reason')=='parent_depth_missing' for s in r['states']))
    def test_sibling_event_cannot_authenticate_parent(self):
        t=self.tx();t['meta']['innerInstructions'][0]['instructions'][1]['stackHeight']=2;r=self.decode(t);self.assertFalse(r['events'])
    def test_nested_other_program_cannot_spoof_event(self):
        t=self.tx();t['meta']['innerInstructions'][0]['instructions'][1]['programIdIndex']=0;r=self.decode(t);self.assertFalse(r['events'])
    def test_missing_child_depth_unresolved(self):
        t=self.tx();t['meta']['innerInstructions'][0]['instructions'][1]['stackHeight']=None;r=self.decode(t);self.assertFalse(r['events']);self.assertTrue(any(s.get('reason')=='subtree_depth_missing' for s in r['states']))
    def test_routed_replay_same_engine_output(self):
        t=self.tx();seq=self.a.append('rpc',response(t),{'method':'getTransaction','params':[t['transaction']['signatures'][0],{'commitment':'confirmed'}]});a=Engine(self.root/'e','mainnet');b=Engine(self.root/'f','mainnet')
        try:a.ingest(self.a,seq,self.g);replay(self.a,b);self.assertEqual(a.export(),b.export());self.assertEqual(a.verify()['events'],1)
        finally:a.close();b.close()
