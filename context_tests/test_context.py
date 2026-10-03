import copy,unittest,tempfile,json,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from brain_tests import test_brain as fixture
from astra_context.runtime import ContextBridge
from astra_context.model import CONFIG,build,classify,score
from astra_context.session import eligible,start_watch,hydration_tick,current_watch
from astra_brain.runtime import BrainBridge
from astra_bridge.session import target
from astra_observer.spine import ReadOnlyRpc,NETWORKS
from observer_tests.test_observer import response,transaction
from astra_dex import pumpswap
from astra_bridge.evidence import WSOL
from astra_context.dataset import freeze,verify,build as dataset
class ContextTests(unittest.TestCase):
    def setUp(self):
        fixture.BrainTests.setUp(self);self.b.close();self.b=ContextBridge(self.a,self.root/'state',self,fixture.fixtures.POLICY,fixture.fixtures.MODEL,10000,1000,brain_config=self.cfg)
    tearDown=fixture.BrainTests.tearDown
    q=fixture.BrainTests.q
    accounts=fixture.BrainTests.accounts
    collect=fixture.BrainTests.collect
    feed=fixture.BrainTests.feed
    def test_context_numeric_after_temporal_window(self):
        self.feed();a=list(self.b.brain_records.values())[-1];self.assertIsNone(a['entry']['score']);self.assertIn('history.minimum_samples',a['entry']['missing_dimensions'])
        self.feed(2);self.feed(3);a=list(self.b.brain_records.values())[-1];self.assertIsNotNone(a['entry']['score']);self.assertEqual(a['state']['market_agent']['context']['span_ns'],2000000000);self.b.verify_replay()
    def test_stale_gap_and_no_zero_substitution(self):
        self.feed();self.feed(30);r=list(self.b.brain_records.values())[-1];self.assertIn('history.continuity',r['entry']['missing_dimensions']);self.assertIsNone(r['entry']['score']);self.assertIsNone(r['state']['market']['executable_depth']['value'])
    def test_contradictory_momentum_blocks_entry(self):
        for n,p in enumerate([100,120,115,110],1):self.feed(n,price=p)
        r=list(self.b.brain_records.values())[-1];self.assertIn('REVERSAL_RISK',r['state']['regime']['labels']);self.assertEqual(r['entry']['action'],'NO_TRADE')
    def test_high_volatility_classified(self):
        for n,p in enumerate([100,200,80],1):self.feed(n,price=p)
        self.assertIn('HIGH_VOLATILITY',list(self.b.brain_records.values())[-1]['state']['regime']['labels'])
    def test_one_red_tick_holds(self):
        for n in range(1,5):self.feed(n)
        self.feed(5,price=103);self.assertEqual(list(self.b.brain_records.values())[-1]['position']['exit']['action'],'HOLD')
    def test_recovery_idempotence(self):
        self.feed();self.feed(2)
        def crash(stage):
            if stage=='ledger_committed':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.feed(3,hook=crash)
        state=self.b.paper.state();self.b.recover();self.b.recover();self.assertEqual(state,self.b.paper.state());self.b.verify_replay()
    def test_freeze_reconstruction(self):
        for n in range(1,6):self.feed(n)
        with tempfile.TemporaryDirectory() as t:
            f=freeze(self.root,t);self.assertEqual(verify(Path(t)/f['freeze_id'])['status'],'PASS');self.assertEqual(f,freeze(self.root,t))
    def test_history_never_changes_old_snapshot(self):
        self.feed();first=copy.deepcopy(next(iter(self.b.brain_records.values())))
        for n in (2,3,4):self.feed(n)
        self.assertEqual(first,next(iter(self.b.brain_records.values())));self.b.verify_replay()
    def poll(self,n,watch,now=None):
        self.at=n*1000000000;tx=transaction(n,100+n);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];tx['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        def call(method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else [{'signature':tx['transaction']['signatures'][0],'slot':tx['slot'],'err':None}] if method=='getSignaturesForAddress' else tx),None
        with patch.object(rpc.rpc,'call',side_effect=call),patch('astra_bridge.runtime.time.time_ns',return_value=self.at),patch('astra_observer.spine.time.time_ns',return_value=self.at):return hydration_tick(self.b,rpc,watch,now_ns=lambda:self.at if now is None else now)
    def test_preentry_hydration_reaches_existing_risk(self):
        self.feed();candidate=eligible(self.b,self.at);self.assertIsNotNone(candidate);w=start_watch(self.b,candidate);self.poll(2,w);self.poll(3,w)
        self.assertEqual(target(self.b)['phase'],'PENDING_BUY');self.assertIsNone(current_watch(self.b));self.b.verify_replay()
    def test_expired_watch_never_requests(self):
        self.feed();w=start_watch(self.b,eligible(self.b,self.at));rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        with patch.object(rpc,'identity',side_effect=AssertionError('network after expiration')):r=hydration_tick(self.b,rpc,w,now_ns=lambda:w['expires_ns'])
        self.assertEqual(r['stopped'],'expired');self.assertEqual(self.b.paper.state()['sequence'],0)
    def test_empty_polls_durable_budget(self):
        self.feed();w=start_watch(self.b,eligible(self.b,self.at));rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        def call(method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else []),None
        with patch.object(rpc.rpc,'call',side_effect=call):
            for _ in range(4):r=hydration_tick(self.b,rpc,w,now_ns=lambda:self.at)
        self.assertEqual(r['stopped'],'budget');self.assertFalse(self.b.paper.state()['pending']);self.assertIsNone(current_watch(self.b))
    def test_expiration_during_evidence_blocks_intent(self):
        self.feed();w=start_watch(self.b,eligible(self.b,self.at));self.feed(2)
        # New observations exist, but evidence collection completes after the watch TTL.
        n=3;self.at=n*1000000000;tx=transaction(n,103);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];tx['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        seq=self.a.append('rpc',response(tx),{'method':'getTransaction','params':[tx['transaction']['signatures'][0],{'commitment':'confirmed'}]},observed_ns=w['expires_ns'])
        self.at=w['expires_ns']
        with patch('astra_bridge.runtime.time.time_ns',return_value=self.at):self.b.ingest(self.a,seq,self.g)
        r=list(self.b.brain_records.values())[-1];self.assertIn('hydration_expired_during_acquisition',r['entry']['reasons']);self.assertEqual(self.b.paper.state()['sequence'],0);self.b.verify_replay()
    def test_future_account_or_event_refused(self):
        self.feed();plan=list(self.b.plans.values())[-1][1];events=self.b._history(plan['event']);future=copy.deepcopy(events);future[0]['availability_ns']+=10
        with self.assertRaisesRegex(ValueError,'context_future'):build(future,plan['event'],None,None,plan['now'],self.cfg)
    def test_hydration_state_survives_new_process(self):
        self.feed();w=start_watch(self.b,eligible(self.b,self.at))
        script="from pathlib import Path;from astra_observer.spine import Archive;from astra_context.runtime import ContextBridge;from astra_context.session import current_watch;from astra_brain.core import DEFAULT;from bridge_tests.test_bridge import POLICY,MODEL;import sys;a=Archive(Path(sys.argv[1])/'raw.sqlite','mainnet');b=ContextBridge(a,Path(sys.argv[1])/'state',None,POLICY,MODEL,10000,1000,brain_config=dict(DEFAULT,max_hold_ns=3000000000,low_liquidity_quote_raw=1));assert current_watch(b)['watch_id']==sys.argv[2];b.recover();b.verify_replay();b.close();a.close()"
        r=subprocess.run([sys.executable,'-B','-c',script,str(self.root),w['watch_id']],capture_output=True,timeout=30);self.assertEqual(r.returncode,0,r.stderr.decode());self.assertEqual(self.b.paper.state()['sequence'],0)
    def test_liquidity_history_and_persistent_deterioration(self):
        from astra_brain.core import position
        for n in range(1,6):self.feed(n)
        r=list(self.b.brain_records.values())[-1];self.assertEqual(r['state']['market']['liquidity_change_bps']['value'],0)
        # Joint persistent negative momentum/flow + reserve decline invalidate thesis.
        s=copy.deepcopy(r['state']);f=s['market_agent']['features'];f['momentum_bps']['value']=-500;f['imbalance_bps']['value']=-8000;f['quote_reserve']['value']=500000000
        pos=next(iter(self.b.paper.state()['positions'].values()));ledger=self.b.paper.export()['ledger'];fill=next(x for x in ledger if x['kind']=='settlement');en=self.b.brain_records[fill['intent_id']]
        p=position(en,pos,fill,s,None,r['state']['clock']['decision_time'],self.cfg,10,0);self.assertEqual(p['exit']['category'],'THESIS_INVALIDATION');self.assertIn('momentum_and_flow_deterioration',p['invalidated_reasons'])
    def test_watch_idempotence_and_closed_watch_no_io(self):
        from astra_context.session import end_watch
        self.feed();c=eligible(self.b,self.at);w=start_watch(self.b,c);before=self.a.audit();self.assertEqual(start_watch(self.b,c),w);self.assertEqual(before,self.a.audit());end_watch(self.b,w,'abandoned')
        rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        with patch.object(rpc,'identity',side_effect=AssertionError('closed watch did IO')):r=hydration_tick(self.b,rpc,w,now_ns=lambda:self.at)
        self.assertEqual(r['stopped'],'closed');self.assertEqual(self.b.paper.state()['sequence'],0)
