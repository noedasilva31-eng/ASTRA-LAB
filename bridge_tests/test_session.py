import json
from unittest.mock import patch
from . import test_bridge as fixtures
from astra_bridge.session import target,follow_once,metrics,DiscoveryPort,FollowupReady,run_session
from astra_observer.spine import ReadOnlyRpc,NETWORKS
from observer_tests.test_observer import response,transaction
from astra_bridge.evidence import WSOL
from astra_dex import pumpswap
import unittest

class SessionTests(unittest.TestCase):
    setUp=fixtures.BridgeTests.setUp
    tearDown=fixtures.BridgeTests.tearDown
    event=fixtures.BridgeTests.event
    q=fixtures.BridgeTests.q
    accounts=fixtures.BridgeTests.accounts
    collect=fixtures.BridgeTests.collect
    feed=fixtures.BridgeTests.feed
    def next_transaction(self,n):
        self.at=n*1_000_000_000;t=transaction(n);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];t['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL;return t
    def poll(self,n):
        tx=self.next_transaction(n);signature=tx['transaction']['signatures'][0];rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200);calls=[]
        def call(method,params):
            calls.append((method,params))
            if method=='getGenesisHash':return response(NETWORKS['mainnet']),None
            if method=='getSignaturesForAddress':return response([{'signature':signature,'slot':tx['slot'],'err':None}]),None
            if method=='getTransaction':return response(tx),None
            raise AssertionError('unexpected method')
        with patch.object(rpc.rpc,'call',side_effect=call),patch('astra_bridge.runtime.time.time_ns',return_value=self.at):r=follow_once(self.a,self.b,rpc,100,clock=lambda:0)
        return r,calls
    def test_followup_targets_committed_intent_pool(self):
        self.feed();pool=target(self.b)['pool'];r,calls=self.poll(2);query=next(p for m,p in calls if m=='getSignaturesForAddress');self.assertEqual(query[0],pool);self.assertEqual(r['matching_events'],1);self.assertEqual(target(self.b)['phase'],'OPEN_POSITION')
    def test_targeted_followup_full_conditional_roundtrip(self):
        self.feed()
        for n in (2,3,4):self.poll(n)
        self.assertIsNone(target(self.b));s=metrics(self.b,1);self.assertEqual(s['state'],'ROUNDTRIP_OBSERVED');self.assertEqual(s['buy_scenarios'],1);self.assertEqual(s['sell_scenarios'],1);self.assertEqual(s['realized_scenario_pnl_quote_raw'],180);self.b.verify_replay()
    def test_discovery_handoff_only_after_committed_intent(self):
        seq,e=self.event()
        with patch('astra_bridge.runtime.time.time_ns',return_value=self.at):
            with self.assertRaises(FollowupReady):DiscoveryPort(self.b).ingest(self.a,seq,self.g)
        self.assertEqual(self.b.paper.state()['sequence'],1);self.assertEqual(len(self.b.results),1)
    def test_empty_followup_never_fills(self):
        self.feed();before=self.b.paper.state();rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        def call(method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else []),None
        with patch.object(rpc.rpc,'call',side_effect=call):r=follow_once(self.a,self.b,rpc,100,clock=lambda:0)
        self.assertEqual(r['hydrated'],0);self.assertEqual(before,self.b.paper.state());self.assertEqual(metrics(self.b,1)['state'],'PENDING_BUY')
    def test_old_rows_not_hydrated(self):
        self.feed();rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        def call(method,params):
            if method=='getTransaction':raise AssertionError('old tx fetched')
            return response(NETWORKS['mainnet'] if method=='getGenesisHash' else [{'slot':100,'signature':'old','err':None}]),None
        with patch.object(rpc.rpc,'call',side_effect=call):r=follow_once(self.a,self.b,rpc,100,clock=lambda:0)
        self.assertEqual(r['old'],1);self.assertEqual(self.b.paper.state()['cash_quote_raw'],10000)
    def test_deadline_stops_hydration_without_fill(self):
        self.feed();rpc=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=200)
        def call(method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else [{'slot':999,'signature':'new','err':None}]),None
        with patch.object(rpc.rpc,'call',side_effect=call):r=follow_once(self.a,self.b,rpc,100,clock=lambda:100)
        self.assertEqual(r['hydrated'],0)
    def test_reopen_followup_uses_durable_intent(self):
        from astra_bridge.runtime import Bridge
        from .test_bridge import POLICY,MODEL
        self.feed();original=target(self.b);self.b.close();self.b=Bridge(self.a,self.root/'state',self,POLICY,MODEL,10000,1000);self.b.recover();self.assertEqual(original,target(self.b));self.poll(2);self.assertEqual(target(self.b)['phase'],'OPEN_POSITION');self.b.verify_replay()
    def test_quote_failure_keeps_pending_and_reason(self):
        self.feed()
        with patch.object(self,'collect',side_effect=ValueError('quote_transport_error')):self.poll(2)
        m=metrics(self.b,1);self.assertEqual(m['state'],'PENDING_BUY');self.assertEqual(m['rejection_counts']['quote_transport_error'],1);self.assertEqual(m['buy_scenarios'],0)
    def test_session_deadline_no_synthetic_progress(self):
        self.feed()
        with patch('astra_bridge.session.time.monotonic',side_effect=[0,2,2]):r=run_session(self.a,self.b,'https://fixture.invalid','wss://fixture.invalid',seconds=1)
        self.assertEqual(r['session']['state'],'PENDING_BUY');self.assertEqual(r['session']['stop_reason'],'bounded_window_ended');self.assertEqual(r['session']['buy_scenarios'],0)
