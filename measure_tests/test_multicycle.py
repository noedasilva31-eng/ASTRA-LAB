import json,subprocess,sys,unittest
from unittest.mock import patch
from bridge_tests import test_bridge as fixtures
from bridge_tests import test_session as sessions
from astra_bridge.runtime import Bridge
from astra_bridge.session import target
from astra_multicycle.session import run,frames,census
from astra_measure.report import generate
class MultiTests(unittest.TestCase):
    setUp=fixtures.BridgeTests.setUp
    tearDown=fixtures.BridgeTests.tearDown
    event=fixtures.BridgeTests.event
    q=fixtures.BridgeTests.q
    accounts=fixtures.BridgeTests.accounts
    collect=fixtures.BridgeTests.collect
    feed=fixtures.BridgeTests.feed
    next_transaction=sessions.SessionTests.next_transaction
    poll=sessions.SessionTests.poll
    def drive(self,seconds=20,max_cycles=2,quiet=False):
        t=[0];n=[len(self.b.results)+1]
        def sleep(v):t[0]+=v
        def discovery():
            if not quiet:self.feed(n[0]);n[0]+=1
            return {'status':'PASS' if not quiet else 'FAIL','code':'real_events_decoded' if not quiet else 'no_supported_event_observed'}
        def follow():
            if quiet:return {'hydrated':0,'matching_events':0,'coverage':'OBSERVED_SUBSET'}
            r,_=self.poll(n[0]);n[0]+=1;return r
        return run(self.a,self.b,'https://fixture.invalid','wss://fixture.invalid',seconds,max_cycles,clock=lambda:t[0],sleep=sleep,discover=discovery,follow=follow)
    def test_two_cycles_and_replay(self):
        r=self.drive();self.assertEqual(r['closed_cycles'],2);self.assertEqual(r['stop_reason'],'cycle_cap_reached');self.assertEqual(self.b.paper.state()['cash_quote_raw'],10360);self.assertEqual(len(frames(self.a,'multi_decision')),8);self.assertEqual(r['discovery_windows'],2);self.b.verify_replay()
        c=generate(self.root)['cycles'];self.assertEqual(len(c),2);self.assertEqual(sum(x['net_quote_raw'] for x in c),360)
    def test_incomplete_three_states_preserved(self):
        for n,phase in ((1,'PENDING_BUY'),(2,'OPEN_POSITION'),(3,'PENDING_SELL')):
            self.feed(n);before=self.b.paper.state();r=self.drive(seconds=1,quiet=True);self.assertEqual(r['state'],phase);self.assertEqual(self.b.paper.state(),before)
    def test_resume_keeps_cap_portfolio_and_idempotent_census(self):
        self.drive();s=self.b.paper.state();count=len(frames(self.a,'multi_decision'));self.b.close();self.b=Bridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000)
        r=self.drive();self.assertEqual(self.b.paper.state(),s);self.assertEqual(r['discovery_windows'],0);self.assertEqual(len(frames(self.a,'multi_decision')),count)
    def test_changed_lifetime_cap_rejected(self):
        self.drive(seconds=1)
        with self.assertRaisesRegex(ValueError,'immutable_multicycle'):self.drive(max_cycles=3)
    def test_no_trade_is_partial_observation(self):
        r=self.drive(seconds=3,quiet=True);self.assertEqual(r['state'],'NO_TRADE');self.assertEqual(r['closed_cycles'],0);self.assertEqual(self.b.paper.state()['sequence'],0)
        d=frames(self.a,'multi_discovery');self.assertTrue(d);self.assertEqual(d[0][1]['coverage'],'OBSERVED_SUBSET');self.assertEqual(d[0][1]['decision'],'NO_TRADE')
    def test_rejects_census_not_unobserved_false_negatives(self):
        self.b.collector=None;self.drive(seconds=3);self.assertTrue(frames(self.a,'multi_decision'));self.assertTrue(all(x['decision']['kind']=='reject' and x['unobserved_opportunities']=='UNKNOWN' for _,x in frames(self.a,'multi_decision')));self.assertEqual(self.b.paper.state()['sequence'],0)
    def test_budget_not_reset_on_resume(self):
        self.drive(seconds=1)
        with self.a.db:self.a.db.execute('UPDATE rpc_budget SET used=200')
        before=self.b.paper.state();r=self.drive();self.assertEqual(r['stop_reason'],'rpc_budget_exhausted');self.assertEqual(r['rpc_budget']['used'],200);self.assertEqual(self.b.paper.state(),before)
    def test_census_recovers_commit_before_scheduler_crash(self):
        self.feed();census(self.a,self.b);census(self.a,self.b);self.assertEqual(len(frames(self.a,'multi_decision')),1)
    def test_pending_resumed_new_process(self):
        self.drive(seconds=1);s=self.b.paper.state()
        script="from pathlib import Path;from astra_observer.spine import Archive;from astra_bridge.runtime import Bridge;from astra_multicycle.session import run;from bridge_tests.test_bridge import POLICY,MODEL;import sys;a=Archive(Path(sys.argv[1])/'raw.sqlite','mainnet');b=Bridge(a,Path(sys.argv[1])/'state',None,POLICY,MODEL,10000,1000);run(a,b,'https://fixture.invalid','wss://fixture.invalid',1,2,clock=iter([0,2,2]).__next__);b.verify_replay();b.close();a.close()"
        p=subprocess.run([sys.executable,'-B','-c',script,str(self.root)],capture_output=True,timeout=30);self.assertEqual(p.returncode,0,p.stderr.decode());self.assertEqual(self.b.paper.state(),s)
    def test_kill_switch_survives_scheduler_resume(self):
        self.b.set_kill(True);self.drive(seconds=2);self.b.close();self.b=Bridge(self.a,self.root/'state',self,fixtures.POLICY,fixtures.MODEL,10000,1000);self.drive(seconds=2)
        self.assertEqual(self.b.paper.state()['positions'],{});self.assertEqual(self.b.paper.state()['cash_quote_raw'],10000)
        self.assertTrue(all('kill_switch' in r['risk']['reasons'] for r in self.b.results.values()));self.b.verify_replay()
    def test_realized_loss_persists_between_cycles_and_resume(self):
        # Different isolated fixture configuration, same unmodified Risk implementation.
        from astra_observer.spine import Archive
        from astra_observer.risk import Policy
        from astra_bridge.evidence import WSOL
        policy=Policy(max_position=5000,min_liquidity=1,max_session_loss=100)
        self.b.close();self.a.close();self.a=Archive(self.root/'loss.sqlite','mainnet')
        from observer_tests.test_observer import response
        from astra_observer.spine import NETWORKS
        self.g=self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash','params':[]},observed_ns=1)
        self.b=Bridge(self.a,self.root/'loss-state',self,policy,fixtures.MODEL,10000,1000)
        def collect(e,side,amount,model):
            x,y=(WSOL,e['base_mint']) if side=='BUY' else (e['base_mint'],WSOL);out=2000 if side=='BUY' else 900
            return {'forward_seq':self.q(e,x,y,amount,out),'reverse_seq':self.q(e,y,x,out,amount),'accounts_seq':self.accounts(e)}
        with patch.object(self,'collect',side_effect=collect):
            self.drive(seconds=5);self.assertEqual(self.b.paper.state()['loss_quote_raw'],120);self.assertEqual(len(self.b.outcome_links()['closed_scenarios']),1)
            self.b.close();self.b=Bridge(self.a,self.root/'loss-state',self,policy,fixtures.MODEL,10000,1000);self.drive(seconds=2)
        self.assertEqual(self.b.paper.state()['loss_quote_raw'],120);self.assertFalse(self.b.paper.state()['positions']);self.assertTrue(any('session_loss_limit' in r.get('risk',{}).get('reasons',[]) for r in self.b.results.values()));self.b.verify_replay()
