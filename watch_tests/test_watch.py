import copy,json,unittest
from unittest.mock import patch
from position_tests import test_position as fixtures
from astra_watch.runtime import activate,WatchBridge
from astra_watch.session import begin,monitor,stage,cursor
from astra_observer.spine import ReadOnlyRpc,NETWORKS
from observer_tests.test_observer import transaction,response
from astra_dex import pumpswap
from astra_bridge.evidence import WSOL
from astra_position.session import run as legacy_run
from astra_position.__main__ import qualification

class WatchTests(unittest.TestCase):
    feed=fixtures.PositionTests.feed
    q=fixtures.PositionTests.q
    accounts=fixtures.PositionTests.accounts
    collect=fixtures.PositionTests.collect
    change=fixtures.PositionTests.change
    def setUp(self):
        fixtures.PositionTests.setUp(self);self.b.close();activate(self.a);self.b=WatchBridge(self.a,self.root/'state',self,**self.kw)
    tearDown=fixtures.PositionTests.tearDown
    def tx(self,n=5,slot=None):
        tx=transaction(n,100+n);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];tx['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        if slot is not None:tx['slot']=slot
        return tx
    def watch(self,tx=None,rows=None,missing=False,window=None,polls=1):
        self.at=5_000_000_000;w=window or begin(self.b,seconds=10,budget=80,max_polls=polls,poll_seconds=1,now=self.at)
        rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80);requests=[]
        def call(method,params):
            requests.append((method,params))
            return response(NETWORKS['mainnet'] if method=='getGenesisHash' else (rows if rows is not None else [{'signature':tx['transaction']['signatures'][0],'slot':tx['slot'],'err':None}]) if method=='getSignaturesForAddress' else None if missing else tx),None
        with patch.object(rpc.rpc,'call',side_effect=call),patch('astra_observer.spine.time.time_ns',return_value=self.at),patch('astra_bridge.runtime.time.time_ns',return_value=self.at):
            d=monitor(self.b,w,rpc=rpc,clock=lambda:0,wall=lambda:self.at,sleep=lambda x:None)
        return d,requests,w
    def test_exact_old_failure_expired_window_zero_calls(self):
        self.a.append('position_window',None,{'started_ns':1,'expires_ns':2});rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        with patch.object(rpc,'identity',side_effect=AssertionError('must not be called')):r=legacy_run(self.b,None,seconds=1,clock=lambda:0,wall=lambda:3,rpc=rpc)
        self.assertEqual(r['rpc_calls_this_invocation'],0);self.assertEqual(qualification(0,r,[])['code'],'no_new_position_observation')
        d,requests,w=self.watch(rows=[]);self.assertTrue(d['network_attempted']);self.assertEqual(d['stage'],'NO_NEW_SIGNATURE');self.assertEqual(requests[1][1],[self.b.activation['target']['pool'],{'limit':32,'commitment':'confirmed'}])
    def test_exact_old_poll_cap_zero_calls(self):
        self.a.append('position_poll_reserved',None,{'index':1});rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        with patch.object(rpc,'identity',side_effect=AssertionError('must not call')):r=legacy_run(self.b,None,seconds=1,max_polls=1,clock=lambda:0,wall=lambda:3,rpc=rpc)
        self.assertEqual(r['stop_reason'],'poll_budget');self.assertEqual(r['rpc_calls_this_invocation'],0)
    def test_no_network_when_same_window_expired(self):
        w=begin(self.b,'fixed',seconds=1,budget=80,max_polls=1,poll_seconds=1,now=1)
        with patch('astra_watch.session.ReadOnlyRpc',side_effect=AssertionError('client')):d=monitor(self.b,w,wall=lambda:2_000_000_000)
        self.assertEqual(d['stage'],'NO_NETWORK_CALL');self.assertEqual(d['stop_reason'],'window_expired')
    def test_no_new_signature_empty_listing(self):
        d,requests,_=self.watch(rows=[]);self.assertEqual(d['stage'],'NO_NEW_SIGNATURE');self.assertTrue(d['signature_search_completed']);self.assertEqual(d['signatures_found'],0);self.assertIsNone(d['latest_slot_seen']);self.b.verify_replay()
    def test_new_signature_missing_transaction(self):
        d,_,_=self.watch(self.tx(),missing=True);self.assertEqual(d['stage'],'NEW_SIGNATURE_NOT_HYDRATED');self.assertEqual(d['hydration_attempts'],1);self.assertEqual(d['transactions_hydrated'],0);self.b.verify_replay()
    def test_new_transaction_unsupported(self):
        tx=self.tx();tx['transaction']['message']['instructions']=[];tx['meta']['innerInstructions']=[]
        d,_,_=self.watch(tx);self.assertEqual(d['stage'],'NEW_TRANSACTION_UNSUPPORTED');self.assertEqual(d['transactions_hydrated'],1);self.b.verify_replay()
    def test_new_observation_rejected_no_ledger_change(self):
        before=self.b.paper.state();self.b.collector=None;d,_,_=self.watch(self.tx());self.assertEqual(d['stage'],'NEW_OBSERVATION_REJECTED');self.assertEqual(d['observations_rejected'],1);self.assertEqual(self.b.paper.state(),before);self.b.verify_replay()
    def test_new_position_observation_hold_continues(self):
        before=self.b.paper.state();d,requests,_=self.watch(self.tx(),polls=2);self.assertEqual(d['stage'],'NEW_POSITION_OBSERVATION');self.assertEqual(d['polls'],2);self.assertEqual(d['transactions_hydrated'],1);self.assertEqual(d['already_processed'],1);self.assertEqual(d['state'],'OPEN_POSITION');self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_freshest_selected_and_no_before_until(self):
        tx=self.tx(7);rows=[{'signature':'older','slot':105,'err':None},{'signature':tx['transaction']['signatures'][0],'slot':107,'err':None}]
        d,req,_=self.watch(tx,rows);self.assertEqual(next(p[0] for m,p in req if m=='getTransaction'),tx['transaction']['signatures'][0]);self.assertEqual(d['latest_slot_seen'],107);self.assertEqual(d['cursor_slot'],104)
    def test_below_cursor_and_failed_explicit(self):
        d,req,_=self.watch(rows=[{'signature':'old','slot':103,'err':None},{'signature':'failed','slot':105,'err':{'InstructionError':1}}]);self.assertEqual(d['below_cursor'],1);self.assertEqual(d['failed_transactions'],1);self.assertFalse(any(m=='getTransaction' for m,p in req))
    def test_same_id_no_reset_new_id_explicit_epoch(self):
        before=self.b.paper.state();d,req,w=self.watch(rows=[]);used=self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0]
        same=begin(self.b,w['window_id'],seconds=10,budget=80,max_polls=1,poll_seconds=1,now=99);self.assertEqual(same,w);self.assertEqual(self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0],used)
        new=begin(self.b,'new',seconds=10,budget=80,max_polls=1,poll_seconds=1,now=10);self.assertEqual(new['previous_budget']['used'],used);self.assertEqual(self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0],0);self.assertEqual(before,self.b.paper.state())
        with self.assertRaisesRegex(ValueError,'superseded'):begin(self.b,w['window_id'],seconds=10,budget=80,max_polls=1,poll_seconds=1)
    def test_restart_reuses_cursor_budget_and_no_buy(self):
        d,_,w=self.watch(self.tx());before=self.b.paper.state();budget=self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0];self.b.close();self.b=WatchBridge(self.a,self.root/'state',self,**self.kw);self.b.recover();self.b.recover();self.assertEqual(before,self.b.paper.state());self.assertEqual(budget,self.a.db.execute('SELECT used FROM rpc_budget').fetchone()[0]);self.b.verify_replay()
    def test_no_endpoint_url_in_diagnostic(self):
        d,_,_=self.watch(rows=[]);text=json.dumps(d);self.assertNotIn('https://',text);self.assertNotIn('fixture.invalid',text);self.assertEqual(d['endpoint_env'],'ASTRA_OBSERVER_RPC_URL')
    def test_reuse_new_id_does_not_duplicate_observation(self):
        d,_,_=self.watch(self.tx());before=self.b.paper.state();d2,req,w=self.watch(self.tx());self.assertEqual(d2['stage'],'NO_NEW_SIGNATURE');self.assertEqual(d2['transactions_hydrated'],0);self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_rpc_failure_visible_not_pool_inactivity(self):
        w=begin(self.b,seconds=1,budget=80,max_polls=1,poll_seconds=1,now=1);rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80)
        with patch.object(rpc.rpc,'call',return_value=(None,'timeout')):d=monitor(self.b,w,rpc=rpc,clock=lambda:0,wall=lambda:1,sleep=lambda x:None)
        self.assertTrue(d['network_attempted']);self.assertFalse(d['signature_search_completed']);self.assertEqual(d['errors'],['rpc_transport_failure'])
    def test_ctrl_c_stops_cleanly_keeps_position(self):
        w=begin(self.b,seconds=1,budget=80,max_polls=1,poll_seconds=1,now=1);rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=80);before=self.b.paper.state()
        with patch.object(rpc.rpc,'call',side_effect=KeyboardInterrupt):d=monitor(self.b,w,rpc=rpc,clock=lambda:0,wall=lambda:1,sleep=lambda x:None)
        self.assertEqual(d['stop_reason'],'operator_interrupted');self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
    def test_bounds_change_same_id_rejected(self):
        begin(self.b,'fixed',seconds=10,budget=80,max_polls=1,poll_seconds=1,now=1)
        with self.assertRaisesRegex(ValueError,'immutable_watch_bounds'):begin(self.b,'fixed',seconds=20,budget=80,max_polls=1,poll_seconds=1,now=1)
    def test_same_slot_unseen_signature_can_be_hydrated(self):
        w=begin(self.b,seconds=10,budget=80,max_polls=1,poll_seconds=1,now=5_000_000_000);self.feed(5)
        w2=begin(self.b,seconds=10,budget=80,max_polls=1,poll_seconds=1,now=5_000_000_000)
        self.assertEqual(w2['cursor']['cursor_slot'],105)
        d,req,_=self.watch(self.tx(6,slot=105),window=w2);self.assertEqual(d['transactions_hydrated'],1);self.assertEqual(d['cursor_slot'],105);self.b.verify_replay()
    def test_expired_legacy_window_does_not_block_new_health(self):
        self.a.append('position_window',None,{'started_ns':1,'expires_ns':2});d,_,_=self.watch(self.tx());self.assertEqual(d['stage'],'NEW_POSITION_OBSERVATION');self.b.verify_replay()
    def test_endpoint_labels_never_echo_credentials(self):
        from astra_watch.__main__ import endpoint_label
        self.assertEqual(endpoint_label('https://mainnet.helius-rpc.com/?api-key=secret'),'mainnet.helius-rpc.com');self.assertEqual(endpoint_label('https://secret.custom.invalid/key'),'CUSTOM_HOST_REDACTED')
    def test_qualified_exit_uses_new_window_not_expired_legacy_window(self):
        self.a.append('position_window',None,{'started_ns':1,'expires_ns':2});begin(self.b,seconds=10,budget=80,max_polls=3,poll_seconds=1,now=5_000_000_000)
        fixtures.PositionTests.deteriorate(self);self.feed(5);self.feed(6)
        self.assertTrue(self.b.paper.state()['pending']);self.feed(7);self.assertFalse(self.b.paper.state()['positions']);self.assertEqual(self.b.paper.state()['cash_quote_raw'],10180);self.b.verify_replay()
    def test_crash_commit_replay_under_watch_no_duplicate(self):
        begin(self.b,seconds=10,budget=80,max_polls=3,poll_seconds=1,now=5_000_000_000);fixtures.PositionTests.deteriorate(self);self.feed(5);self.feed(6)
        def stop(stage):
            if stage=='ledger_committed':raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):self.feed(7,hook=stop)
        before=self.b.paper.state();self.b.close();self.b=WatchBridge(self.a,self.root/'state',self,**self.kw);self.b.recover();self.b.recover();self.assertEqual(before,self.b.paper.state());self.b.verify_replay()
