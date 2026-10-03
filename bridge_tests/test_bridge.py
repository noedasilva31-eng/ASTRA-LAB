import copy,json,tempfile,unittest,time,base64,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from astra_bridge.evidence import WSOL,bindings,opportunity,accounts_proof,Quotes,EvidenceRpc
from astra_bridge.runtime import Bridge,Collector,reason
from astra_observer.spine import Archive,NETWORKS,canonical,decode_frame
from astra_observer.risk import Policy
from astra_execution.paper import Model
from astra_pipeline.decode import TOKEN
from astra_dex import pumpswap
from observer_tests.test_observer import transaction,response
POLICY=Policy(max_position=5000,min_liquidity=1)
MODEL=Model(fee_quote_raw=10,adverse_bps=0)
class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=Archive(self.root/'raw.sqlite','mainnet');self.g=self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash','params':[]},observed_ns=1)
        self.b=Bridge(self.a,self.root/'state',self,POLICY,MODEL,10000,1000);self.at=1_000_000_000
    def tearDown(self):self.b.close();self.a.close();self.tmp.cleanup()
    def event(self,n=1):
        self.at=n*1_000_000_000;t=transaction(n);names=pumpswap.SCHEMA['instructions']['buy']['accounts'];t['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        seq=self.a.append('rpc',response(t),{'method':'getTransaction','params':[t['transaction']['signatures'][0],{'commitment':'confirmed','encoding':'json','maxSupportedTransactionVersion':1}]},observed_ns=self.at)
        return seq,decode_frame(self.a,seq,self.g)['events'][0]
    def q(self,e,x,y,amount,output):
        v={'inputMint':x,'outputMint':y,'inAmount':str(amount),'outAmount':str(output),'otherAmountThreshold':str(output),'swapMode':'ExactIn','slippageBps':0,'priceImpactPct':'0.001','contextSlot':e['slot'],'routePlan':[{'percent':100,'swapInfo':{'ammKey':e['pool'],'inputMint':x,'outputMint':y}}]}
        return self.a.append('quote',canonical(v).encode(),{'provider':'jupiter-v1','request':{'inputMint':x,'outputMint':y,'amount':amount,'slippageBps':0}},observed_ns=self.at)
    def accounts(self,e):
        def mint():return {'owner':TOKEN,'executable':False,'data':{'parsed':{'type':'mint','info':{'isInitialized':True,'mintAuthority':None,'freezeAuthority':None}}}}
        def vault(m):return {'owner':TOKEN,'executable':False,'data':{'parsed':{'type':'account','info':{'mint':m,'owner':e['pool'],'state':'initialized','tokenAmount':{'amount':'1000000000'}}}}}
        return self.a.append('rpc',response({'context':{'slot':e['slot']},'value':[mint(),mint(),vault(e['base_mint']),vault(WSOL),{'owner':pumpswap.PROGRAM,'executable':False}]}),{'method':'getMultipleAccounts','params':[bindings(self.a,e),{'commitment':'confirmed','encoding':'jsonParsed','minContextSlot':e['slot']}]},observed_ns=self.at)
    def collect(self,e,side,amount,model):
        x,y=(WSOL,e['base_mint']) if side=='BUY' else (e['base_mint'],WSOL);out=2000 if side=='BUY' else 1200
        return {'forward_seq':self.q(e,x,y,amount,out),'reverse_seq':self.q(e,y,x,out,amount),'accounts_seq':self.accounts(e)}
    def feed(self,n=1,hook=None):
        seq,e=self.event(n)
        with patch('astra_bridge.runtime.time.time_ns',return_value=self.at):self.b.ingest(self.a,seq,self.g,hook)
        return seq,e
    def proof(self):
        _,e=self.event();refs=self.collect(e,'BUY',1000,MODEL);return e,refs
    def op(self,e,refs,now=None):return opportunity(self.a,e,'BUY',1000,**refs,now=self.at if now is None else now,policy=POLICY,model=MODEL)
    def change(self,seq,fn):
        f,_=self.a.frame(seq);raw=json.loads(base64.b64decode(f['raw']));fn(raw);return self.a.append(f['kind'],canonical(raw).encode(),f['metadata'],observed_ns=f['observed_ns'])
    def test_positive_bound_evidence(self):
        e,r=self.proof();o=self.op(e,r);self.assertEqual(o['authority_state'],'OBSERVED_SAFE');self.assertEqual(o['feed_coverage'],'PARTIAL');self.assertIn('NOT_EXECUTION',o['execution_quote']['assurance'])
    def test_roundtrip_from_events_and_replay(self):
        for n in range(1,5):self.feed(n)
        s=self.b.paper.state();self.assertEqual(s['cash_quote_raw'],10180);self.assertEqual(s['realized_scenario_pnl_quote_raw'],180);self.assertFalse(s['positions']);self.assertEqual(self.b.verify_replay()['status'],'PASS');links=self.b.outcome_links();self.assertEqual(links['closed_scenarios'][0]['realized_scenario_pnl_quote_raw'],180);self.assertEqual(len(links['decision_census']),4)
    def test_no_evidence_no_fill_census_preserved(self):
        self.b.collector=None;self.feed();self.assertEqual(self.b.paper.state()['sequence'],0);self.assertEqual(len(self.b.engine.export()['pools']),1);self.assertEqual(next(iter(self.b.results.values()))['kind'],'reject');self.b.verify_replay()
    def test_duplicate_does_not_requote_or_publish(self):
        seq,e=self.feed()
        with patch.object(self,'collect',side_effect=AssertionError('duplicate fetch')):self.b.ingest(self.a,seq,self.g)
        self.assertEqual(self.b.paper.state()['sequence'],1);self.assertEqual(len(self.b.plans),1)
    def test_prepared_crash_recovers_original_time(self):
        def stop(stage):
            if stage=='prepared':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.feed(hook=stop)
        self.assertEqual(self.b.paper.state()['sequence'],0);self.b.recover();self.b.recover();self.assertEqual(self.b.paper.state()['sequence'],1);self.b.verify_replay()
    def test_ledger_committed_crash_no_double_publish(self):
        def stop(stage):
            if stage=='ledger_committed':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.feed(hook=stop)
        self.assertEqual(self.b.paper.state()['sequence'],1);self.b.recover();self.assertEqual(self.b.paper.state()['sequence'],1);self.b.verify_replay()
    def test_recovery_new_process(self):
        def stop(stage):
            if stage=='prepared':raise RuntimeError('stop')
        with self.assertRaises(RuntimeError):self.feed(hook=stop)
        code="from pathlib import Path;from astra_observer.spine import Archive;from astra_bridge.runtime import Bridge;from bridge_tests.test_bridge import POLICY,MODEL;import sys;a=Archive(Path(sys.argv[1])/'raw.sqlite','mainnet');b=Bridge(a,Path(sys.argv[1])/'state',None,POLICY,MODEL,10000,1000);b.recover();b.verify_replay();b.close();a.close()"
        p=subprocess.run([sys.executable,'-B','-c',code,str(self.root)],capture_output=True,timeout=30);self.assertEqual(p.returncode,0,p.stderr.decode());self.assertEqual(self.b.paper.state()['sequence'],1)
    def test_mint_authority_veto(self):
        e,r=self.proof();r['accounts_seq']=self.change(r['accounts_seq'],lambda v:v['result']['value'][0]['data']['parsed']['info'].update(mintAuthority=e['wallet']))
        with self.assertRaisesRegex(ValueError,'authority_present'):self.op(e,r)
    def test_freeze_authority_veto(self):
        e,r=self.proof();r['accounts_seq']=self.change(r['accounts_seq'],lambda v:v['result']['value'][0]['data']['parsed']['info'].update(freezeAuthority=e['wallet']))
        with self.assertRaisesRegex(ValueError,'authority_present'):self.op(e,r)
    def test_wrong_vault_owner_veto(self):
        e,r=self.proof();r['accounts_seq']=self.change(r['accounts_seq'],lambda v:v['result']['value'][2]['data']['parsed']['info'].update(owner=e['wallet']))
        with self.assertRaisesRegex(ValueError,'vault_identity'):self.op(e,r)
    def test_extensions_veto(self):
        e,r=self.proof();r['accounts_seq']=self.change(r['accounts_seq'],lambda v:v['result']['value'][0]['data']['parsed']['info'].update(extensions=[{'unknown':True}]))
        with self.assertRaisesRegex(ValueError,'extensions'):self.op(e,r)
    def test_null_account_veto(self):
        e,r=self.proof();r['accounts_seq']=self.change(r['accounts_seq'],lambda v:v['result']['value'].__setitem__(0,None))
        with self.assertRaisesRegex(ValueError,'account_missing'):self.op(e,r)
    def test_different_pool_quote_veto(self):
        e,r=self.proof();r['forward_seq']=self.change(r['forward_seq'],lambda v:v['routePlan'][0]['swapInfo'].update(ammKey=e['wallet']))
        with self.assertRaisesRegex(ValueError,'route_pool'):self.op(e,r)
    def test_price_impact_veto(self):
        e,r=self.proof();r['forward_seq']=self.change(r['forward_seq'],lambda v:v.update(priceImpactPct='0.2'))
        with self.assertRaisesRegex(ValueError,'price_impact'):self.op(e,r)
    def test_stale_and_future_veto(self):
        e,r=self.proof()
        for now in (self.at-1,self.at+6_000_000_000):
            with self.assertRaisesRegex(ValueError,'stale_or_future'):self.op(e,r,now)
    def test_reverse_size_must_cover_inventory(self):
        e,r=self.proof();r['reverse_seq']=self.q(e,e['base_mint'],WSOL,1999,1000)
        with self.assertRaisesRegex(ValueError,'reverse_quote_size'):self.op(e,r)
    def test_forged_event_veto(self):
        e,r=self.proof();e['wallet']='forged'
        with self.assertRaisesRegex(ValueError,'event_evidence'):self.op(e,r)
    def test_raw_corruption_fail_closed(self):
        self.feed();self.a.db.execute('DROP TRIGGER no_UPDATE_frames');self.a.db.execute("UPDATE frames SET document='{}' WHERE seq=1");self.a.db.commit()
        with self.assertRaises(ValueError):self.b.verify_replay()
    def test_kill_switch_rechecked_no_fill(self):
        self.feed();self.b.set_kill(True);self.feed(2);self.assertEqual(self.b.paper.state()['cash_quote_raw'],10000);self.assertEqual(list(self.b.results.values())[-1]['kind'],'reject');self.b.verify_replay()
    def test_unsafe_exception_text_not_persisted(self):self.assertNotIn('secret',reason(ValueError('https://example.invalid?key=secret')))
    def test_unprepared_crash_is_explicit_reject(self):
        seq,e=self.event();self.b.engine.ingest(self.a,seq,self.g);self.b.recover();self.assertEqual(next(iter(self.b.results.values()))['code'],'interrupted_before_evidence_plan');self.assertEqual(self.b.paper.state()['sequence'],0);self.b.verify_replay()
    def test_minimum_liquidity_risk_veto(self):
        original=self.accounts
        def low(e):return self.change(original(e),lambda v:v['result']['value'][3]['data']['parsed']['info']['tokenAmount'].update(amount='1'))
        with patch.object(self,'accounts',low):self.feed()
        self.assertEqual(self.b.paper.state()['cash_quote_raw'],10000);self.assertFalse(self.b.paper.state()['positions']);self.assertEqual(next(iter(self.b.results.values()))['kind'],'reject')
    def test_failed_exit_quote_preserves_inventory(self):
        self.feed();self.feed(2);before=self.b.paper.state()
        with patch.object(self,'collect',side_effect=ValueError('quote_transport_error')):self.feed(3)
        self.assertEqual(before,self.b.paper.state());self.assertEqual(list(self.b.results.values())[-1]['kind'],'reject');self.b.verify_replay()
    def test_rpc_accounts_budget_and_readonly(self):
        seq,e=self.event();rpc=EvidenceRpc(self.a,'https://fixture.invalid',limit=1)
        with patch.object(rpc.rpc,'call',return_value=(response(NETWORKS['mainnet']),None)):rpc.identity()
        with self.assertRaisesRegex(ValueError,'quota_exhausted'):rpc.accounts(bindings(self.a,e),e['slot'])
        with self.assertRaisesRegex(ValueError,'read_only'):rpc.call('sendTransaction',[])
    def test_quote_secret_echo_not_archived(self):
        EvidenceRpc(self.a,'https://fixture.invalid',limit=2)
        q=Quotes(self.a,key='my-private-key',interval=0)
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return b'{"error":"my-private-key"}'
        with patch.object(q.opener,'open',return_value=Response()):
            with self.assertRaisesRegex(ValueError,'credential_echo'):q.get(WSOL,pumpswap.PROGRAM,1)
        self.assertNotIn('my-private-key',''.join(r[0] for r in self.a.db.execute('SELECT document FROM frames')))
    def test_quote_timeout_no_fill_and_failure_archived(self):
        EvidenceRpc(self.a,'https://fixture.invalid',limit=2);q=Quotes(self.a,interval=0)
        with patch.object(q.opener,'open',side_effect=TimeoutError()):
            with self.assertRaisesRegex(ValueError,'transport_error'):q.get(WSOL,pumpswap.PROGRAM,1)
        f=json.loads(self.a.db.execute('SELECT document FROM frames ORDER BY seq DESC LIMIT 1').fetchone()[0]);self.assertIsNone(f['raw']);self.assertEqual(f['metadata']['error'],'quote_transport_error')
    def test_plan_corruption_detected(self):
        self.feed();self.a.db.execute('DROP TRIGGER no_UPDATE_frames');self.a.db.execute("UPDATE frames SET document='{}' WHERE seq=(SELECT max(seq) FROM frames)");self.a.db.commit()
        with self.assertRaises(ValueError):self.b.verify_replay()
    def test_immutable_configuration(self):
        with self.assertRaisesRegex(ValueError,'immutable_bridge'):Bridge(self.a,self.root/'new',None,POLICY,MODEL,10000,999)
    def test_session_lock_rejects_second_writer(self):
        from astra_bridge.__main__ import writer_lock
        with writer_lock(self.root):
            with self.assertRaisesRegex(ValueError,'writer_already'): 
                with writer_lock(self.root):pass
    def test_same_slot_fill_rejected_then_later_retry(self):
        self.feed();original=self.q
        def old_slot(e,*args):
            modified=dict(e,slot=101);return original(modified,*args)
        with patch.object(self,'q',old_slot):self.feed(2)
        self.assertEqual(self.b.paper.state()['cash_quote_raw'],10000);self.assertTrue(self.b.paper.state()['pending']);self.feed(3);self.assertTrue(self.b.paper.state()['positions']);self.b.verify_replay()
    def test_gate_real_missing_is_not_pass(self):
        import bridge_validation
        target=self.root/'gate.json'
        with patch.dict('os.environ',{},clear=True):self.assertEqual(bridge_validation.main(target),1)
        report=json.loads(target.read_text());self.assertTrue(all(c['status']=='NOT_EXECUTED' for c in report['checks'][:2]))
    def test_stream_adapter_drives_paper_and_census(self):
        from astra_observer.source import stream
        t=transaction();names=pumpswap.SCHEMA['instructions']['buy']['accounts'];t['transaction']['message']['accountKeys'][names.index('quote_mint')]=WSOL
        signature=t['transaction']['signatures'][0]
        class WS:
            def __init__(self):self.frames=iter([json.dumps({'id':1,'result':7}),json.dumps({'method':'logsNotification','params':{'subscription':7,'result':{'value':{'signature':signature}}}})])
            def send(self,x):pass
            def settimeout(self,x):pass
            def recv(self):return next(self.frames)
            def close(self):pass
        def rpc(client,method,params):return response(NETWORKS['mainnet'] if method=='getGenesisHash' else t),None
        with patch('astra_blocks.rpc.Rpc.call',rpc),patch('astra_bridge.runtime.time.time_ns',return_value=self.at):r=stream(self.a,self.b,'https://fixture.invalid','wss://fixture.invalid',max_messages=1,limit=200,connect=lambda *a,**k:WS())
        self.assertEqual(r['events'],1);self.assertEqual(self.b.paper.state()['sequence'],1);self.assertEqual(len(self.b.engine.export()['pools']),1);self.b.verify_replay()
    def test_interleaved_collector_genesis_replay(self):
        self.feed(1)
        self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash','params':[]},observed_ns=self.at+1)
        self.feed(2)
        self.assertEqual(self.b.verify_replay()['status'],'PASS')
    def test_actual_collector_identity_interleaving_with_failed_quotes(self):
        self.b.collector=Collector(self.a,'https://fixture.invalid')
        with patch.object(self.b.collector.rpc.rpc,'call',return_value=(response(NETWORKS['mainnet']),None)),patch.object(self.b.collector.quotes,'get',side_effect=ValueError('quote_transport_error')):
            self.feed(1);self.feed(2)
        self.assertEqual(self.b.verify_replay()['status'],'PASS');self.assertEqual(self.b.paper.state()['sequence'],0)
        self.assertTrue(all(r['code']=='quote_transport_error' for r in self.b.results.values()))
    def test_unknown_valueerror_is_software_failure_not_market_reject(self):
        from astra_bridge.diagnostics import diagnose
        with patch.object(self,'collect',side_effect=ValueError('private secret endpoint')):
            with self.assertRaises(ValueError) as caught:self.feed()
        detail=diagnose(caught.exception,'collect_evidence');self.assertEqual(detail['category'],'SOFTWARE_EXCEPTION');self.assertNotIn('private',json.dumps(detail));self.assertEqual(len(self.b.plans),0)
    def test_integrity_error_code_preserved_without_secrets(self):
        from astra_bridge.diagnostics import diagnose
        d=diagnose(ValueError('materialization_replay_mismatch'),'offline_reconstruction');self.assertEqual(d['code'],'materialization_replay_mismatch');self.assertEqual(d['category'],'INTEGRITY_FAILURE')
    def test_validator_preserves_software_failure_and_location(self):
        import bridge_validation
        target=self.root/'diagnostic.json';failure={'status':'FAIL','code':'bridge_software_exception','category':'SOFTWARE_EXCEPTION','exception_type':'ValueError','location':{'file':'astra_bridge/evidence.py','function':'collect','line':42},'diagnostic':{'stage':'stream_and_evidence'}}
        with patch.dict('os.environ',{'ASTRA_OBSERVER_NETWORK':'mainnet','ASTRA_OBSERVER_RPC_URL':'https://fixture.invalid','ASTRA_OBSERVER_WS_URL':'wss://fixture.invalid'}),patch('bridge_validation.run',return_value=failure):bridge_validation.main(target)
        checks=json.loads(target.read_text())['checks'];self.assertTrue(all(c['status']=='FAIL' for c in checks[:2]));self.assertEqual(checks[0]['location']['line'],42);self.assertEqual(checks[0]['category'],'SOFTWARE_EXCEPTION')
    def test_validator_market_insufficiency_not_decoding_pass(self):
        import bridge_validation
        target=self.root/'market.json';r={'status':'PASS','code':'real_events_decoded','state':{'plans':[],'paper':{'ledger':[]},'results':{'id':{'kind':'reject','code':'mint_or_freeze_authority_present'}}}}
        with patch.dict('os.environ',{'ASTRA_OBSERVER_NETWORK':'mainnet','ASTRA_OBSERVER_RPC_URL':'https://fixture.invalid','ASTRA_OBSERVER_WS_URL':'wss://fixture.invalid'}),patch('bridge_validation.run',return_value=r):bridge_validation.main(target)
        checks=json.loads(target.read_text())['checks'];self.assertEqual(checks[0]['status'],'FAIL');self.assertEqual(checks[0]['category'],'EVIDENCE_REJECT');self.assertEqual(checks[1]['status'],'NOT_EXECUTED')
