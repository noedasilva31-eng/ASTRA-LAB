import json,tempfile,unittest
from pathlib import Path
from . import test_brain as fixtures
from astra_brain.dataset import build,freeze,verify
from astra_brain.research import candidate,comparison_contract
class DatasetTests(unittest.TestCase):
    setUp=fixtures.BrainTests.setUp
    tearDown=fixtures.BrainTests.tearDown
    q=fixtures.BrainTests.q
    accounts=fixtures.BrainTests.accounts
    collect=fixtures.BrainTests.collect
    feed=fixtures.BrainTests.feed
    def test_freeze_exact_reconstruction_and_repeated_identity(self):
        for n in range(1,9):self.feed(n)
        with tempfile.TemporaryDirectory() as tmp:
            a=freeze(self.root,tmp);b=freeze(self.root,tmp);self.assertEqual(a,b);self.assertEqual(verify(Path(tmp)/a['freeze_id'])['status'],'PASS')
    def test_dataset_repeat_and_no_trade_outcomes(self):
        for n in range(1,10):self.feed(n,price=100)
        a=build(self.root);b=build(self.root);self.assertEqual(a,b);self.assertEqual(a['cycles'],[]);self.assertEqual(len(a['decisions']),9);self.assertTrue(any(o['status']=='DERIVED' for o in a['outcomes']));self.assertTrue(any(o['status']=='UNKNOWN' for o in a['outcomes']));self.assertTrue(all(not o['executable_outcome'] for o in a['outcomes']))
    def test_freeze_tampering_rejected(self):
        self.feed()
        with tempfile.TemporaryDirectory() as tmp:
            f=freeze(self.root,tmp);folder=Path(tmp)/f['freeze_id'];(folder/'dataset.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'freeze_file_hash'):verify(folder)
    def test_latency_tails_not_extrapolated(self):
        self.feed();d=build(self.root);m=d['latencies']['market_agent_ns'];self.assertEqual(m['samples'],1);self.assertIsNone(m['p95_ns']);self.assertIsNone(m['p99_ns']);self.assertGreaterEqual(m['p50_ns'],0)
    def test_research_candidate_no_promotion(self):
        c=candidate('baseline','hypothesis','REMOVE',{'feature':'market'},'freeze');self.assertEqual(c['live_promotion'],'UNAVAILABLE');self.assertEqual(set(c['stages'].values()),{'NOT_EXECUTED'});self.assertEqual(comparison_contract('b',c['candidate_id'])['status'],'NOT_EXECUTED')
    def test_incomplete_position_in_dataset(self):
        for n in range(1,5):self.feed(n)
        d=build(self.root);self.assertTrue(d['positions']);self.assertEqual(d['cycles'],[])
