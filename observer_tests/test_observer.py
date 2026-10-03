import base64,copy,json,os,sqlite3,struct,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from astra_observer.spine import Archive,ReadOnlyRpc,NETWORKS,canonical,decode_frame,sha
from astra_observer.engine import Engine,replay
from astra_observer.risk import Policy,evaluate
from astra_observer.source import stream,safe_frame,search
from astra_dex import pumpswap
from operations_tests.test_dex import fixture
ROOT=Path(__file__).resolve().parents[1]
def response(v):return canonical({'jsonrpc':'2.0','id':1,'result':v}).encode()
def transaction(n=1,price=100):
    t,f=fixture('buy');t['slot']=100+n;t['blockTime']=1000+n;t['transaction']['signatures']=[pumpswap.b58encode(bytes([n%250+1])*64)]
    f['user_quote_amount_in']=price;f['quote_amount_in']=price;spec=pumpswap.SCHEMA['events']['BuyEvent'];raw=bytes(spec['discriminator'])
    for field in spec['fields']:
        v=f[field['name']];typ=field['type']
        if typ=='pubkey':raw+=pumpswap.b58decode(v)
        elif typ=='bool':raw+=bytes([int(v)])
        elif typ=='string':b=v.encode();raw+=struct.pack('<I',len(b))+b
        else:raw+=int(v).to_bytes(int(typ[1:])//8,'little',signed=typ.startswith('i'))
    t['meta']['innerInstructions'][0]['instructions'][0]['data']=pumpswap.b58encode(pumpswap.EVENT_TAG+raw);return t
class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=Archive(self.root/'raw.sqlite','mainnet');self.g=self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash','params':[]},observed_ns=1);self.e=Engine(self.root/'engine.sqlite','mainnet',horizons=(1,2),window=4)
    def tearDown(self):self.e.close();self.a.close();self.tmp.cleanup()
    def frame(self,n=1,price=100,at=1000000000):
        t=transaction(n,price);return self.a.append('rpc',response(t),{'method':'getTransaction','params':[t['transaction']['signatures'][0],{'commitment':'confirmed','encoding':'json','maxSupportedTransactionVersion':1}]},observed_ns=at)
    def test_mainnet_genesis_required(self):
        bad=self.a.append('rpc',response(NETWORKS['devnet']),{'method':'getGenesisHash'})
        with self.assertRaisesRegex(ValueError,'genesis_mismatch'):decode_frame(self.a,self.frame(),bad)
    def test_network_cannot_change(self):
        with self.assertRaisesRegex(ValueError,'network_mismatch'):Archive(self.root/'raw.sqlite','devnet')
    def test_readonly_and_budget_reserved_before_io(self):
        r=ReadOnlyRpc(self.a,'https://fixture.invalid',limit=1)
        with self.assertRaisesRegex(ValueError,'read_only'):r.call('sendTransaction',[])
        with patch.object(r.rpc,'call',return_value=(response(NETWORKS['mainnet']),None)) as call:
            r.identity()
            with self.assertRaisesRegex(ValueError,'quota_exhausted'):r.transaction('x')
            self.assertEqual(call.call_count,1)
    def test_null_is_unresolved(self):
        seq=self.a.append('rpc',response(None),{'method':'getTransaction','params':['signature',{'commitment':'confirmed'}]},observed_ns=2)
        self.assertEqual(decode_frame(self.a,seq,self.g)['states'][0]['status'],'unresolved')
    def test_census_before_strategy_and_outcomes_for_no_trade(self):
        self.e.ingest(self.a,self.frame(),self.g);before=self.e.export();self.assertEqual(len(before['pools']),1);self.assertEqual(before['decisions'][0]['action'],'NO_TRADE');self.assertEqual(before['outcomes'][0]['status'],'NOT_COLLECTED')
        self.e.ingest(self.a,self.frame(2,200,2_000_000_000),self.g);out=self.e.export()['outcomes'][0];self.assertEqual(out['observed_mark_return'],{'numerator':'1','denominator':'1'});self.assertEqual(out['liquidable_price']['status'],'NOT_COLLECTED');self.assertEqual(out['coverage'],'PARTIAL')
    def test_replay_same_decisions_features_outcomes(self):
        for n in range(1,4):self.e.ingest(self.a,self.frame(n,n*100,n*1_000_000_000),self.g)
        target=Engine(self.root/'replay.sqlite','mainnet',horizons=(1,2),window=4)
        try:replay(self.a,target);self.assertEqual(self.e.export(),target.export())
        finally:target.close()
    def test_repeat_delivery_does_not_republish(self):
        seq=self.frame();self.e.ingest(self.a,seq,self.g);seq2=self.frame(at=2_000_000_000);self.e.ingest(self.a,seq2,self.g);self.assertEqual(self.e.verify()['events'],1)
    def test_event_identity_conflict_refused(self):
        self.e.ingest(self.a,self.frame(),self.g)
        with self.assertRaisesRegex(ValueError,'identity_conflict'):self.e.ingest(self.a,self.frame(price=300),self.g)
    def test_transaction_signature_bound_to_request(self):
        t=transaction();seq=self.a.append('rpc',response(t),{'method':'getTransaction','params':['different',{'commitment':'confirmed'}]})
        with self.assertRaisesRegex(ValueError,'signature_mismatch'):decode_frame(self.a,seq,self.g)
    def test_historical_decision_does_not_gain_future_data(self):
        self.e.ingest(self.a,self.frame(),self.g);before=self.e.export()['decisions'][0];self.e.ingest(self.a,self.frame(2,200,2_000_000_000),self.g)
        after=next(d for d in self.e.export()['decisions'] if d['event_id']==before['event_id']);self.assertEqual(before,after);self.assertEqual(len(after['opportunity']['feature_events']),1)
    def test_fixed_feature_window(self):
        for n in range(1,8):self.e.ingest(self.a,self.frame(n,100,n*1_000_000_000),self.g)
        s=self.e.export()['pools'][0];self.assertEqual(len(s['window']),4);self.assertEqual(s['events'],7)
    def test_clock_regression_fail_closed(self):
        self.e.ingest(self.a,self.frame(at=200),self.g)
        with self.assertRaisesRegex(ValueError,'clock_regression'):self.e.ingest(self.a,self.frame(2,at=199),self.g)
        self.assertEqual(self.e.verify()['events'],1)
    def test_crash_atomicity(self):
        seq=self.frame()
        def stop(stage):
            if stage=='before_commit':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.e.ingest(self.a,seq,self.g,stop)
        self.assertEqual(self.e.verify()['events'],0);self.e.ingest(self.a,seq,self.g);self.assertEqual(self.e.verify()['events'],1)
    def test_recovery_new_process(self):
        seq=self.frame();code="import os,sys;from astra_observer.spine import Archive;from astra_observer.engine import Engine\na=Archive(sys.argv[1],'mainnet');e=Engine(sys.argv[2],'mainnet',horizons=(1,2),window=4)\ndef hook(stage):\n if stage=='committed':os._exit(73)\ne.ingest(a,int(sys.argv[3]),1,hook)"
        p=subprocess.run([sys.executable,'-B','-c',code,str(self.root/'raw.sqlite'),str(self.root/'engine.sqlite'),str(seq)],cwd=ROOT,timeout=20,capture_output=True);self.assertEqual(p.returncode,73);self.e.ingest(self.a,seq,self.g);self.assertEqual(self.e.verify()['events'],1)
    def test_raw_corruption_detected(self):
        self.a.db.execute('DROP TRIGGER no_UPDATE_frames');self.a.db.execute("UPDATE frames SET document='{}' WHERE seq=1");self.a.db.commit()
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):self.a.audit()
    def test_risk_limits_frozen(self):
        with self.assertRaisesRegex(ValueError,'immutable_engine_configuration'):Engine(self.root/'engine.sqlite','mainnet',policy=Policy(max_position=2000000),horizons=(1,2),window=4)
    def test_no_heavy_timeline_in_hot_path(self):
        with patch('astra_timeline.store.Timeline.verify',side_effect=AssertionError('heavy audit called')):self.e.ingest(self.a,self.frame(),self.g)
    def test_unknown_social_never_zero(self):
        self.e.ingest(self.a,self.frame(),self.g);s=self.e.export()['decisions'][0]['opportunity'];self.assertEqual(s['social'],{'status':'NOT_COLLECTED'});self.assertIsNone(s['pool_creation_time'])
    def test_empty_search_is_failure(self):
        def fake(client,method,params):return (response(NETWORKS['mainnet'] if method=='getGenesisHash' else []),None)
        with patch('astra_blocks.rpc.Rpc.call',fake):r=search(self.a,self.e,'https://fixture.invalid',limit=4,max_signatures=2)
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['events'],0)
    def test_ws_echo_not_archived(self):
        with self.assertRaisesRegex(ValueError,'credential_echo_rejected'):safe_frame(b'{"result":"secret1234"}','wss://fixture.invalid?key=secret1234')
    def test_stream_hydration_same_engine(self):
        t=transaction();signature=t['transaction']['signatures'][0]
        class WS:
            def __init__(self):self.frames=iter([json.dumps({'jsonrpc':'2.0','id':1,'result':1}),json.dumps({'jsonrpc':'2.0','method':'logsNotification','params':{'subscription':1,'result':{'context':{'slot':101},'value':{'signature':signature,'err':None,'logs':[]}}}})])
            def send(self,x):pass
            def settimeout(self,x):pass
            def recv(self):return next(self.frames)
            def close(self):pass
        def rpc(client,method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else t),None
        with patch('astra_blocks.rpc.Rpc.call',rpc):r=stream(self.a,self.e,'https://fixture.invalid','wss://fixture.invalid',max_messages=1,limit=3,connect=lambda *a,**k:WS())
        self.assertEqual(r['events'],1);self.assertEqual(r['coverage'],'PARTIAL');self.assertEqual(self.e.latencies()['decode_ns']['samples'],1)

class RiskTests(unittest.TestCase):
    def good(self):return {'availability_ns':10,'heartbeat_ns':10,'data_health':'OBSERVED','coverage':'OBSERVED','authority_state':'OBSERVED_SAFE','execution_quote':{'status':'OBSERVED','exit_possible':True,'provenance':{'fixture':True},'expires_ns':30,'observed_ns':10,'size_raw':100,'liquidity_quote_raw':10000000,'slippage_bps':10}}
    def test_all_prerequisites_needed(self):
        s=self.good();a={'exposure':0,'positions':0,'loss':0};self.assertTrue(evaluate(s,a,100,20,Policy())['allowed']);s['authority_state']='NOT_COLLECTED';self.assertFalse(evaluate(s,a,100,20,Policy())['allowed'])
    def test_kill_and_loss(self):
        r=evaluate(self.good(),{'exposure':0,'positions':0,'loss':100000},100,20,Policy(),kill=True);self.assertIn('kill_switch',r['reasons']);self.assertIn('session_loss_limit',r['reasons'])
    def test_all_position_limits(self):
        r=evaluate(self.good(),{'exposure':2000000,'positions':2,'loss':0},1000001,20,Policy());self.assertIn('position_limit',r['reasons']);self.assertIn('exposure_limit',r['reasons']);self.assertIn('positions_limit',r['reasons'])
    def test_stale_and_liquidity_and_slippage(self):
        s=self.good();s['execution_quote'].update(liquidity_quote_raw=0,slippage_bps=1000);r=evaluate(s,{'exposure':0,'positions':0,'loss':0},100,10**12,Policy());self.assertIn('stale_or_future_data',r['reasons']);self.assertIn('quote_expired',r['reasons']);self.assertIn('slippage_bps_limit_or_missing',r['reasons']);self.assertIn('liquidity_quote_raw_limit_or_missing',r['reasons'])

class ReplayIntegrityTests(unittest.TestCase):
    setUp=ObserverTests.setUp
    tearDown=ObserverTests.tearDown
    frame=ObserverTests.frame
    # Reuse fixture helpers, only expose new tests (inherited cases also run intentionally).
    def test_materialized_state_corruption_detected(self):
        self.e.ingest(self.a,self.frame(),self.g);self.e.verify_reconstruction(self.a)
        self.e.db.execute("UPDATE pools SET state='{}'");self.e.db.commit()
        with self.assertRaisesRegex(ValueError,'materialization_replay_mismatch'):self.e.verify_reconstruction(self.a)
    def test_error_history_survives_later_success(self):
        self.a.append('rpc',canonical({'jsonrpc':'2.0','id':1,'error':{'code':-32603,'message':'internal'}}).encode(),{'method':'getTransaction','params':['x',{'commitment':'confirmed'}]},observed_ns=2)
        seq=self.frame();r=replay(self.a,self.e);self.assertTrue(any(x.get('reason')=='rpc_error' for x in r['states']));self.assertEqual(self.e.verify()['events'],1)
