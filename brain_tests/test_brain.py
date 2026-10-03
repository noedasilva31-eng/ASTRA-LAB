import copy,json,tempfile,unittest
from unittest.mock import patch
from bridge_tests import test_bridge as fixtures
from observer_tests.test_observer import transaction,response
from astra_bridge.evidence import WSOL
from astra_observer.spine import decode_frame,sha
from astra_dex import pumpswap
from astra_brain.runtime import BrainBridge
from astra_brain.core import DEFAULT,datum,market,regime,scores,entry,position,meta_state
from astra_measure.report import generate
class BrainTests(unittest.TestCase):
    def setUp(self):
        fixtures.BridgeTests.setUp(self);self.b.close();self.cfg=dict(DEFAULT,max_hold_ns=3_000_000_000,low_liquidity_quote_raw=1);self.b=BrainBridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000,brain_config=self.cfg)
    tearDown=fixtures.BridgeTests.tearDown
    q=fixtures.BridgeTests.q
    accounts=fixtures.BridgeTests.accounts
    collect=fixtures.BridgeTests.collect
    def feed(self,n=1,price=None,hook=None):
        self.at=n*1_000_000_000;t=transaction(n,100+n if price is None else price);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];t['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        seq=self.a.append('rpc',response(t),{'method':'getTransaction','params':[t['transaction']['signatures'][0],{'commitment':'confirmed','encoding':'json','maxSupportedTransactionVersion':1}]},observed_ns=self.at)
        with patch('astra_bridge.runtime.time.time_ns',return_value=self.at):self.b.ingest(self.a,seq,self.g,hook)
        return seq
    def test_entry_hold_time_exit_and_replay(self):
        for n in range(1,9):self.feed(n)
        kinds=[r['kind'] for r in self.b.results.values()];self.assertEqual(kinds,['no_trade','no_trade','intent','settlement','hold','hold','intent','settlement'])
        self.assertEqual(self.b.paper.state()['cash_quote_raw'],10180);self.b.verify_replay();r=generate(self.root);self.assertEqual(len(r['cycles']),1)
    def test_two_successive_brain_cycles(self):
        for n in range(1,15):self.feed(n)
        self.assertEqual(len(self.b.outcome_links()['closed_scenarios']),2);self.b.verify_replay()
    def test_red_candle_does_not_exit(self):
        for n in range(1,5):self.feed(n)
        self.feed(5,price=103);last=list(self.b.brain_records.values())[-1];self.assertEqual(last['position']['exit']['action'],'HOLD');self.assertEqual(len(self.b.paper.state()['positions']),1)
    def test_unchanged_price_no_trade_and_scored(self):
        for n in range(1,5):self.feed(n,price=100)
        self.assertFalse(self.b.paper.state()['positions']);self.assertTrue(all(r['kind']=='no_trade' for r in self.b.results.values()));self.assertEqual(len(self.b.brain_records),4);self.b.verify_replay()
    def test_risk_veto_despite_high_score(self):
        self.b.set_kill(True)
        for n in range(1,4):self.feed(n)
        r=list(self.b.brain_records.values())[-1];self.assertEqual(r['entry']['action'],'CANDIDATE_BUY');self.assertFalse(r['state']['risk']['allowed']);self.assertEqual(list(self.b.results.values())[-1]['kind'],'reject');self.assertFalse(self.b.paper.state()['positions'])
    def test_missing_evidence_keeps_features_scores_and_reject(self):
        self.b.collector=None;self.feed();r=next(iter(self.b.brain_records.values()));self.assertEqual(r['action'],'REJECT');self.assertIsNone(r['state']['scores']['ExecutionScoreV0']['value']);self.assertEqual(self.b.paper.state()['sequence'],0);self.b.verify_replay()
    def test_future_and_stale_unknown(self):
        with self.assertRaisesRegex(ValueError,'future'):datum(1,5,6)
        self.assertEqual(datum(0,5,5)['status'],'FRESH');self.assertIsNone(datum(None,5)['value']);self.assertEqual(datum(1,10_000_000_000,1)['status'],'STALE');self.assertEqual(meta_state(5)['status'],'UNKNOWN')
    def test_frozen_snapshot_no_lookahead(self):
        self.feed();first=copy.deepcopy(next(iter(self.b.brain_records.values())))
        for n in range(2,5):self.feed(n)
        self.assertEqual(first,next(iter(self.b.brain_records.values())));self.b.verify_replay()
    def test_configuration_version_immutable(self):
        self.feed();self.b.close()
        with self.assertRaisesRegex(ValueError,'immutable_brain'):BrainBridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000,brain_config=dict(self.cfg,entry_score=6001))
        self.b=BrainBridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000,brain_config=self.cfg)
    def test_crash_after_commit_idempotent_and_replay(self):
        for n in range(1,4):self.feed(n)
        def crash(stage):
            if stage=='ledger_committed':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.feed(4,hook=crash)
        before=self.b.paper.state();self.b.close();self.b=BrainBridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000,brain_config=self.cfg);self.b.recover();self.b.recover();self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_prepared_crash_recovers_original_snapshot(self):
        self.feed();self.feed(2)
        def crash(stage):
            if stage=='prepared':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.feed(3,hook=crash)
        self.b.recover();self.assertEqual(len(self.b.brain_records),3);self.assertEqual(self.b.paper.state()['sequence'],1);self.b.verify_replay()
    def test_duplicate_no_new_snapshot_or_fill(self):
        for n in range(1,5):seq=self.feed(n)
        state=self.b.paper.state();frames=self.a.audit();self.b.ingest(self.a,seq,self.g);self.assertEqual(state,self.b.paper.state());self.assertEqual(frames,self.a.audit())
    def test_position_health_and_exit_rules(self):
        for n in range(1,6):self.feed(n)
        r=list(self.b.brain_records.values())[-1];p=r['position'];self.assertEqual(p['health']['version'],'PositionHealthScoreV0');self.assertEqual(p['exit']['action'],'HOLD');self.assertEqual(p['observed_swap_price_extrema']['classification'],'DERIVED');self.assertFalse(p['observed_swap_price_extrema']['executable'])
        en=self.b.brain_records[next(iter(self.b.paper.export()['ledger']))['id']];pos=next(iter(self.b.paper.state()['positions'].values()));fill=next(x for x in self.b.paper.export()['ledger'] if x['kind']=='settlement');s=copy.deepcopy(r['state']);now=r['state']['clock']['decision_time']
        s['risk']={'allowed':False,'reasons':['kill_switch']};z=position(en,pos,fill,s,None,now,self.cfg,10);self.assertEqual(z['exit']['action'],'EXIT_CANDIDATE');self.assertIn('HARD_RISK_EXIT',z['exit']['category'])
        s['risk']={'allowed':True,'reasons':[]};s['market_agent']['features']['quote_reserve']['value']=1;s['market_agent']['features']['momentum_bps']['value']=-500;s['market_agent']['features']['imbalance_bps']['value']=-8000
        z=position(en,pos,fill,s,None,now,self.cfg,10);self.assertEqual(z['exit']['category'],'THESIS_INVALIDATION')
        s['market_agent']['features']['momentum_bps']['value']=0;z=position(en,pos,fill,s,None,now,self.cfg,10);self.assertEqual(z['exit']['action'],'REDUCE_CANDIDATE');self.assertFalse(z['exit']['partial_execution_supported'])
    def test_scoring_formula_explained_reproducible(self):
        for n in range(1,4):self.feed(n)
        r=list(self.b.brain_records.values())[-1];s=r['state'];again=scores(s['market_agent']['features'],s['clock']['decision_time'],self.cfg);self.assertEqual(again,s['scores'])
        for v in again.values():self.assertEqual(sum(c['weight'] for c in v['components']),100);self.assertIn('NOT_FIT_TO_VSOF',v['weights_status'])
        broken=copy.deepcopy(s['market_agent']['features']);broken['momentum_bps']['status']='STALE';self.assertIsNone(scores(broken,s['clock']['decision_time'],self.cfg)['OpportunityScoreV0']['value'])
    def test_bounded_scheduler_preserves_pending(self):
        from astra_multicycle.session import run
        for n in range(1,4):self.feed(n)
        before=self.b.paper.state();r=run(self.a,self.b,'https://fixture.invalid','wss://fixture.invalid',seconds=1,max_opportunities=3,clock=lambda:0)
        self.assertEqual(r['state'],'PENDING_BUY');self.assertEqual(r['stop_reason'],'opportunity_cap_reached');self.assertEqual(before,self.b.paper.state())
    def test_restart_in_new_process(self):
        import subprocess,sys
        for n in range(1,5):self.feed(n)
        script="from pathlib import Path;from astra_observer.spine import Archive;from astra_brain.runtime import BrainBridge;from astra_brain.core import DEFAULT;from bridge_tests.test_bridge import POLICY,MODEL;import sys;a=Archive(Path(sys.argv[1])/'raw.sqlite','mainnet');b=BrainBridge(a,Path(sys.argv[1])/'state',None,POLICY,MODEL,10000,1000,brain_config=dict(DEFAULT,max_hold_ns=3000000000,low_liquidity_quote_raw=1));b.recover();b.verify_replay();b.close();a.close()"
        before=self.b.paper.state();p=subprocess.run([sys.executable,'-B','-c',script,str(self.root)],capture_output=True,timeout=30);self.assertEqual(p.returncode,0,p.stderr.decode());self.assertEqual(before,self.b.paper.state())
