import copy,json,tempfile,unittest,hashlib,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from context_tests import test_context as context_fixture
from bridge_tests.test_bridge import POLICY,MODEL
from bridge_tests import test_bridge as bridge_fixture
from astra_position.runtime import PositionBridge
from astra_position.resume import prepare
from astra_position.health import analyze
from astra_position.session import run,TargetCollector
from astra_observer.spine import Archive,ReadOnlyRpc,NETWORKS
from astra_bridge.session import target
from observer_tests.test_observer import response

class PositionTests(unittest.TestCase):
    q=bridge_fixture.BridgeTests.q
    accounts=bridge_fixture.BridgeTests.accounts
    collect=bridge_fixture.BridgeTests.collect
    change=bridge_fixture.BridgeTests.change
    feed=context_fixture.ContextTests.feed
    def setUp(self):
        context_fixture.ContextTests.setUp(self)
        for n in range(1,5):self.feed(n)
        self.kw={'policy':POLICY,'model':MODEL,'initial':10000,'size':1000,'brain_config':self.cfg}
        ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        self.b.close();self.a.close();src=self.root
        self.resume_tmp=tempfile.TemporaryDirectory();dst=Path(self.resume_tmp.name)/'session'
        prepare(src,dst,bridge_kwargs=self.kw);self.source=src;self.root=dst;self.a=Archive(dst/'raw.sqlite','mainnet');self.b=PositionBridge(self.a,dst/'state',self,**self.kw)
    def tearDown(self):
        self.b.close();self.a.close();self.resume_tmp.cleanup();self.tmp.cleanup()
    def reopen(self):
        self.b.close();self.b=PositionBridge(self.a,self.root/'state',self,**self.kw);self.b.recover()
    def last(self):return list(self.b.health_records.values())[-1]['health']
    def deteriorate(self):
        original_q=self.q;original_a=self.accounts
        self.q=lambda *args:self.change(original_q(*args),lambda v:v.update(priceImpactPct='0.01'))
        self.accounts=lambda e:self.change(original_a(e),lambda v:v['result']['value'][3]['data']['parsed']['info']['tokenAmount'].update(amount='500000000'))
    def test_exact_resume_and_idempotence(self):
        before=self.b.paper.export();self.reopen();self.b.recover();self.assertEqual(before,self.b.paper.export());self.assertEqual(self.b.verify_replay()['status'],'PASS')
        self.assertEqual(prepare(self.source,self.root,bridge_kwargs=self.kw)['portfolio'],before['state'])
    def test_isolated_red_then_recovery_no_timer_sell(self):
        self.feed(5,price=90);self.assertEqual(self.last()['action'],'HOLD');self.feed(6,price=105);self.feed(70,price=106)
        self.assertEqual(len(self.b.paper.state()['positions']),1);self.assertFalse(self.b.paper.state()['pending']);self.b.verify_replay()
    def test_persistent_joint_exit_and_post_decision_settlement(self):
        self.deteriorate();self.feed(5);self.assertEqual(self.last()['action'],'HOLD');self.feed(6);self.assertEqual(self.last()['action'],'EXIT_CANDIDATE');self.assertEqual(target(self.b)['phase'],'PENDING_SELL')
        self.feed(7);self.assertIsNone(target(self.b));self.assertEqual(self.b.paper.state()['cash_quote_raw'],10180);self.assertEqual(len(self.b.outcome_links()['closed_scenarios']),1);self.b.verify_replay()
    def test_evidence_refusal_preserves_inventory(self):
        self.b.collector=None;before=self.b.paper.state();self.feed(5);self.assertEqual(before,self.b.paper.state());self.assertNotEqual(self.last()['action'],'EXIT_CANDIDATE');self.b.verify_replay()
    def test_risk_refuses_exit(self):
        self.deteriorate();self.feed(5);self.b.set_kill(True);self.feed(6);self.assertEqual(self.last()['action'],'VETO');self.assertFalse(self.b.paper.state()['pending']);self.b.verify_replay()
    def test_settlement_risk_refusal_keeps_pending(self):
        self.deteriorate();self.feed(5);self.feed(6);before=self.b.paper.state();self.b.set_kill(True);self.feed(7);self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_crash_after_sell_commit_recover_no_duplicate(self):
        self.deteriorate();self.feed(5);self.feed(6)
        def crash(stage):
            if stage=='ledger_committed':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.feed(7,hook=crash)
        before=self.b.paper.state();self.reopen();self.b.recover();self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_crash_prepared_plan_recovers(self):
        self.feed(5)
        def crash(stage):
            if stage=='prepared':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):self.feed(6,hook=crash)
        self.reopen();self.assertEqual(len(self.b.health_records),2);self.b.verify_replay()
    def test_duplicate_no_requote_health_or_ledger(self):
        seq=self.feed(5);before=self.a.audit();ledger=self.b.paper.state()
        with patch.object(self,'collect',side_effect=AssertionError('requote')):self.b.ingest(self.a,seq,self.g)
        self.assertEqual(before,self.a.audit());self.assertEqual(ledger,self.b.paper.state())
    def test_post_close_no_new_buy(self):
        self.deteriorate();self.feed(5);self.feed(6);self.feed(7);before=self.b.paper.state();self.feed(8);self.assertEqual(before,self.b.paper.state());self.assertEqual(list(self.b.results.values())[-1]['code'],'position_only_no_new_buy');self.b.verify_replay()
    def pure(self,mutate=None,previous=None):
        if not self.b.health_records:self.feed(5)
        r=list(self.b.brain_records.values())[-1];s=copy.deepcopy(r['state']);s['clock']['decision_time']+=1
        if mutate:mutate(s)
        pos=next(iter(self.b.paper.state()['positions'].values()));fill=next(x for x in self.b.paper.export()['ledger'] if x['kind']=='settlement');entry=self.b.brain_records[fill['intent_id']]
        return analyze(entry,pos,fill,s,s['market_agent']['observed_price_samples'],previous or [],None,self.cfg,MODEL,POLICY)
    def test_flow_reversal_alone_not_exit(self):
        h=self.pure(lambda s:s['market']['imbalance_bps'].update(value=-9000));self.assertEqual(h['thesis_state'],'WEAKENING');self.assertEqual(h['action'],'HOLD')
    def test_liquidity_disappearance_alone_not_exit(self):
        h=self.pure(lambda s:s['market']['quote_reserve'].update(value=1));self.assertTrue(h['signals']['liquidity_deterioration']);self.assertEqual(h['action'],'HOLD')
    def test_stale_unknown_not_zero(self):
        h=self.pure(lambda s:s['market']['momentum_bps'].update(status='STALE'));self.assertIn('momentum_bps',h['missing']);self.assertEqual(h['thesis_state'],'UNKNOWN');self.assertIsNone(h['metrics']['executable_depth']['value'])
    def test_impact_alone_not_exit(self):
        h=self.pure(lambda s:s['market']['quote_impact_bps'].update(value=150));self.assertTrue(h['signals']['execution_deterioration']);self.assertEqual(h['action'],'HOLD')
    def test_mae_mfe_observed_not_executable(self):
        self.feed(5,price=90);h=self.last();self.assertIsNotNone(h['metrics']['mae_observed_bps']['value']);self.assertFalse(h['metrics']['mae_observed_bps']['executable']);self.assertEqual(h['metrics']['observed_samples']['value'],1)
    def test_poll_budget_persistent_no_discovery(self):
        rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        with patch.object(rpc.rpc,'call',side_effect=lambda method,params:(response(NETWORKS['mainnet'] if method=='getGenesisHash' else []),None)):
            r=run(self.b,None,seconds=1,max_polls=2,clock=lambda:0,wall=lambda:10,sleep=lambda x:None,rpc=rpc)
            self.assertEqual(r['stop_reason'],'poll_budget');self.assertEqual(r['polls_reserved'],2);spent=r['rpc_budget']['used']
            r2=run(self.b,None,seconds=1,max_polls=2,clock=lambda:0,wall=lambda:10,sleep=lambda x:None,rpc=rpc);self.assertEqual(r2['rpc_budget']['used'],spent);self.assertEqual(r2['state'],'OPEN_POSITION')
    def test_expired_window_no_requests(self):
        self.a.append('position_window',None,{'started_ns':1,'expires_ns':2});rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        with patch.object(rpc,'identity',side_effect=AssertionError('network')):r=run(self.b,None,seconds=1,clock=lambda:0,wall=lambda:3,rpc=rpc)
        self.assertEqual(r['polls_reserved'],0);self.assertEqual(r['state'],'OPEN_POSITION')
    def test_budget_cannot_refill_on_restart(self):
        with self.a.db:self.a.db.execute('UPDATE rpc_budget SET used=79')
        self.reopen();prepare(self.source,self.root,bridge_kwargs=self.kw);self.assertEqual(self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0],79)
    def test_corruption_replay_fails(self):
        self.feed(5);self.a.db.execute('DROP TRIGGER no_UPDATE_frames');self.a.db.execute("UPDATE frames SET hash='bad' WHERE seq=1");self.a.db.commit()
        with self.assertRaises(ValueError):self.b.verify_replay()
    def test_expiration_during_evidence_no_intent(self):
        self.deteriorate();self.feed(5);self.a.append('position_window',None,{'started_ns':1,'expires_ns':5500000000});self.feed(6);self.assertEqual(list(self.b.results.values())[-1]['code'],'position_window_expired_during_acquisition');self.assertFalse(self.b.paper.state()['pending']);self.b.verify_replay()
    def test_future_observation_refused(self):
        self.feed(5);r=list(self.b.brain_records.values())[-1];state=copy.deepcopy(r['state']);samples=copy.deepcopy(state['market_agent']['observed_price_samples']);samples[-1]['available_at']=state['clock']['decision_time']+1
        pos=next(iter(self.b.paper.state()['positions'].values()));fill=next(x for x in self.b.paper.export()['ledger'] if x['kind']=='settlement');entry=self.b.brain_records[fill['intent_id']]
        with self.assertRaisesRegex(ValueError,'future_sample'):analyze(entry,pos,fill,state,samples,[],None,self.cfg,MODEL,POLICY)
    def test_review_closed_cycle_includes_costs_and_health(self):
        from astra_position.report import build
        self.deteriorate();self.feed(5);self.feed(6);self.feed(7);r=build(self.root);self.assertEqual(r['cycles'][0]['net_quote_raw'],180);self.assertEqual(r['cycles'][0]['exit_reason']['rule'],'PositionBrainV0.2');self.assertFalse(r['promotion_allowed'])
    def test_persistent_flow_momentum_and_liquidity_invalidate(self):
        def decline(s):
            s['market']['momentum_bps']['value']=-500;s['market']['imbalance_bps']['value']=-9000;s['market']['quote_reserve']['value']=500000000
        first=self.pure(decline);self.assertEqual(first['action'],'HOLD')
        def again(s):
            decline(s);s['clock']['decision_time']+=1000000000;s['identity']['event_id']='next-observation'
        second=self.pure(again,[first]);self.assertEqual(second['thesis_state'],'INVALIDATED');self.assertEqual(second['action'],'EXIT_CANDIDATE')
    def test_target_collector_refuses_other_pool_before_network(self):
        c=TargetCollector(self,'target','mint')
        with patch.object(self,'collect',side_effect=AssertionError('network')):
            with self.assertRaisesRegex(ValueError,'pending_other_token'):c.collect({'pool':'other','base_mint':'mint'},'SELL',1,MODEL)
    def test_targeted_poll_hydrates_same_pool_without_discovery(self):
        from observer_tests.test_observer import transaction
        from astra_dex import pumpswap
        from astra_bridge.evidence import WSOL
        tx=transaction(5,105);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];tx['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        self.at=5000000000;rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        def call(method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else [{'signature':tx['transaction']['signatures'][0],'slot':tx['slot'],'err':None}] if method=='getSignaturesForAddress' else tx),None
        with patch.object(rpc.rpc,'call',side_effect=call),patch('astra_bridge.runtime.time.time_ns',return_value=self.at),patch('astra_observer.spine.time.time_ns',return_value=self.at):
            r=run(self.b,None,seconds=1,max_polls=1,clock=lambda:0,wall=lambda:self.at,sleep=lambda x:None,rpc=rpc)
        self.assertEqual(r['hydrations'],1);self.assertEqual(r['new_matching_observations'],1);self.assertEqual(r['state'],'OPEN_POSITION');self.assertEqual(self.last()['action'],'HOLD');self.b.verify_replay()
    def test_expiration_after_raw_keeps_reconstruction_without_quote(self):
        from observer_tests.test_observer import transaction
        from astra_dex import pumpswap
        from astra_bridge.evidence import WSOL
        tx=transaction(5,105);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];tx['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        self.at=5000000000;rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80);elapsed=[0]
        def call(method,params):
            if method=='getTransaction':elapsed[0]=2
            return response(NETWORKS['mainnet'] if method=='getGenesisHash' else [{'signature':tx['transaction']['signatures'][0],'slot':tx['slot'],'err':None}] if method=='getSignaturesForAddress' else tx),None
        before=self.b.paper.state()
        with patch.object(rpc.rpc,'call',side_effect=call),patch('astra_bridge.runtime.time.time_ns',return_value=self.at),patch('astra_observer.spine.time.time_ns',return_value=self.at),patch.object(self,'collect',side_effect=AssertionError('quote after deadline')):
            r=run(self.b,None,seconds=1,max_polls=1,clock=lambda:elapsed[0],wall=lambda:self.at,sleep=lambda x:None,rpc=rpc)
        self.assertEqual(r['stop_reason'],'window_expired_after_raw');self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
