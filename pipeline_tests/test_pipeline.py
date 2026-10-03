import copy,json,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.rpc import Rpc,canonical,DEVNET_GENESIS
from astra_blocks.store import BlockStore
from astra_budget.store import Budget
from astra_pipeline.rpc import BudgetRpc
from astra_pipeline.decode import TOKEN,enrich,verify_dataset
from astra_pipeline.run import run,offline
from astra_pipeline.store import Index,export
from astra_provenance.archive import capture_source,bundle
from memory_tests.test_memory import tx,b58,A,B,OTHER
from block_tests.test_blocks import block,context,response
ROOT=Path(__file__).resolve().parents[1]

def token_tx():
    t=tx();t['transaction']['message']['accountKeys']=[A,OTHER,B,A,TOKEN]
    t['transaction']['message']['instructions']=[{'programIdIndex':4,'accounts':[0,1,2,3],'data':b58(struct.pack('<BQB',12,12,6))}]
    def bal(i,v):return {'accountIndex':i,'mint':OTHER,'owner':A,'programId':TOKEN,'uiTokenAmount':{'amount':str(v),'decimals':6}}
    t['meta'].update(fee=5000,preTokenBalances=[bal(0,100),bal(2,0)],postTokenBalances=[bal(0,88),bal(2,12)])
    return t

def rich_block(slot=100,parent=99,transaction=None):
    v=json.loads(block(slot,parent));t=token_tx() if transaction is None else transaction;t['transaction']['signatures']=[b58(bytes([slot%255 or 1])*64)]
    v['result']['transactions']=[t];return canonical(v).encode()
def fake_call(self,method,params):
    if method=='getGenesisHash':return response(DEVNET_GENESIS),None
    if method=='getSlot':return response(200),None
    return rich_block(params[0],params[0]-1),None
def factory(b):return BudgetRpc(b,'https://fixture.invalid')
class PipelineTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def value(self,t=None):
        p=self.root/'source.sqlite';s=BlockStore(p,100,100)
        try:s.apply(s.capture(100,s.session(context()),rich_block(transaction=t)))
        finally:s.close()
        return enrich(bundle(capture_source(p)))
    def test_spl_and_exact_balance_deltas(self):
        v=self.value();self.assertEqual(v['payload']['metrics']['event_kinds'],{'spl_transfer_checked':1,'token_balance_change':2})
        deltas=[e['event']['delta_raw'] for e in v['payload']['events'] if e['event']['kind']=='token_balance_change'];self.assertEqual(sorted(deltas),['-12','12']);self.assertEqual(v['payload']['transactions'][0]['fee_lamports'],'5000')
    def test_missing_balance_is_unknown_not_zero(self):
        t=token_tx();t['meta']['preTokenBalances']=[];v=self.value(t)
        for e in v['payload']['events']:
            if e['event']['kind']=='token_balance_change':self.assertIsNone(e['event']['delta_raw']);self.assertFalse(e['event']['delta_known'])
        self.assertEqual(v['payload']['metrics']['token_balance_partial'],1)
    def test_token_metadata_absent_counted(self):
        t=token_tx();del t['meta']['preTokenBalances'];self.assertEqual(self.value(t)['payload']['metrics']['token_balance_not_recorded'],1)
    def test_failed_transaction_emits_no_transfer(self):
        t=token_tx();t['meta']['err']={'InstructionError':[0,'Custom']};v=self.value(t);self.assertEqual(v['payload']['events'],[]);self.assertEqual(v['payload']['metrics']['transactions']['failed'],1)
    def test_large_units_no_float(self):
        t=token_tx();t['meta']['preTokenBalances'][0]['uiTokenAmount']['amount']=str(2**64-1)
        v=self.value(t);e=next(x['event'] for x in v['payload']['events'] if x['event'].get('account')==A);self.assertEqual(e['delta_raw'],str(88-(2**64-1)))
    def test_invalid_decimals_fail_closed(self):
        t=token_tx();t['meta']['preTokenBalances'][0]['uiTokenAmount']['decimals']=True;v=self.value(t);self.assertEqual(v['payload']['metrics']['transactions']['error'],1);self.assertEqual(v['payload']['events'],[])
    def test_invalid_instruction_accounts_is_error(self):
        t=token_tx();t['transaction']['message']['instructions'][0]['accounts'][0]=999;v=self.value(t);self.assertEqual(v['payload']['metrics']['instruction_errors'],1)
    def test_metadata_change_no_fabricated_delta(self):
        t=token_tx();t['meta']['postTokenBalances'][0]['mint']=B;v=self.value(t);e=next(x['event'] for x in v['payload']['events'] if x['event'].get('account')==A);self.assertFalse(e['delta_known'])
    def test_u64_corruption_rejected(self):
        t=token_tx();t['meta']['postTokenBalances'][0]['uiTokenAmount']['amount']=str(2**64);self.assertEqual(self.value(t)['payload']['metrics']['transactions']['error'],1)
    def test_replay_and_exports_identical(self):
        v=self.value();verify_dataset(v);export(v,self.root/'a');export(v,self.root/'b')
        for p in (self.root/'a').iterdir():self.assertEqual(p.read_bytes(),(self.root/'b'/p.name).read_bytes())
    def test_changed_business_data_rejected(self):
        v=self.value();v['payload']['events'][0]['event']['kind']='fake'
        with self.assertRaises(ValueError):verify_dataset(v)
    def test_pipeline_quota_applies_to_context_and_blocks(self):
        with patch.object(Rpc,'call',fake_call):r=run(self.root/'work',limit=10,start=100,end=101,client_factory=factory)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['quota']['requests'],4);self.assertEqual(r['business']['index']['unique_events'],6)
    def test_quota_exhaustion_before_transport(self):
        calls=[]
        def tracked(client,method,params):calls.append(method);return fake_call(client,method,params)
        with patch.object(Rpc,'call',tracked):r=run(self.root/'work',limit=3,start=100,end=101,client_factory=factory)
        self.assertEqual(r['code'],'quota_exhausted');self.assertEqual(len(calls),3);self.assertEqual(r['blocks']['counts']['archived'],1);self.assertEqual(r['blocks']['unresolved'],1)
    def test_restart_does_not_republish(self):
        with patch.object(Rpc,'call',fake_call):
            a=run(self.root/'work',limit=20,start=100,end=101,max_slots=1,client_factory=factory)
            b=run(self.root/'work',limit=20,client_factory=factory)
            c=run(self.root/'work',limit=20,client_factory=factory)
        self.assertEqual(a['status'],'FAIL');self.assertEqual(b['status'],'PASS');self.assertEqual(c['business']['index']['unique_events'],6)
    def test_offline_new_process_after_crash(self):
        v=self.value();source=self.root/'source.sqlite'
        for phase in ('captured','base_published','business_published'):
            out=self.root/phase
            code="import os,sys;from astra_pipeline.run import offline\ndef hook(p):\n if p==sys.argv[3]:os._exit(73)\noffline(sys.argv[1],sys.argv[2],hook)"
            p=subprocess.run([sys.executable,'-B','-c',code,str(source),str(out),phase],cwd=ROOT,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.assertEqual(p.returncode,73)
            result=offline(source,out);self.assertEqual(result['status'],'PASS');self.assertEqual(result['index']['unique_events'],3)
    def test_index_atomic_rollback_and_corruption(self):
        v=self.value();idx=Index(self.root/'business.sqlite')
        try:
            def fail():raise RuntimeError('crash')
            with self.assertRaises(RuntimeError):idx.publish(v,fail)
            self.assertEqual(idx.audit()['datasets'],0);idx.publish(v);idx.publish(v);self.assertEqual(idx.audit()['unique_events'],3)
            idx.db.execute('DROP TRIGGER no_UPDATE_business_events');idx.db.execute("UPDATE business_events SET document='{}'");idx.db.commit();self.assertFalse(idx.audit()['healthy'])
        finally:idx.close()
    def test_export_corruption_not_overwritten(self):
        v=self.value();export(v,self.root/'exports');p=self.root/'exports'/(v['dataset_sha256']+'.json');p.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):export(v,self.root/'exports')

    def test_comparison_same_archive_not_independent_provider_claim(self):
        from astra_pipeline.compare import compare
        v=self.value();c=compare(v,v);self.assertTrue(c['consistent_over_union']);self.assertFalse(c['provider_independence_verified']);self.assertEqual(c['counts']['match'],1)
    def test_comparison_detects_conflicting_block(self):
        from astra_pipeline.compare import compare
        a=self.value();p=self.root/'other.sqlite';s=BlockStore(p,100,100)
        try:
            raw=json.loads(rich_block());raw['result']['blockhash']='conflict';s.apply(s.capture(100,s.session(context()),canonical(raw).encode()))
        finally:s.close()
        c=compare(a,enrich(bundle(capture_source(p))));self.assertFalse(c['consistent_over_union']);self.assertEqual(c['counts']['block_conflict'],1)
    def test_shared_budget_across_workspaces(self):
        budget=self.root/'shared.sqlite'
        with patch.object(Rpc,'call',fake_call):
            a=run(self.root/'one',limit=4,start=100,end=100,client_factory=factory,budget_path=budget)
            b=run(self.root/'two',limit=4,start=101,end=101,client_factory=factory,budget_path=budget)
        self.assertEqual(a['status'],'PASS');self.assertEqual(b['code'],'quota_exhausted');self.assertEqual(b['quota']['requests'],4)
    def test_completed_run_no_additional_rpc(self):
        with patch.object(Rpc,'call',fake_call):a=run(self.root/'one',limit=4,start=100,end=100,client_factory=factory)
        with patch.object(Rpc,'call',side_effect=AssertionError('unexpected network')):b=run(self.root/'one',limit=4,client_factory=factory)
        self.assertEqual(a['quota']['requests'],b['quota']['requests']);self.assertEqual(a['business']['dataset_id'],b['business']['dataset_id'])

    def test_comparison_missing_overlap_not_agreement(self):
        from astra_pipeline.compare import compare
        a=self.value();p=self.root/'different-range.sqlite';s=BlockStore(p,101,101)
        try:s.apply(s.capture(101,s.session(context()),rich_block(101,100)))
        finally:s.close()
        c=compare(a,enrich(bundle(capture_source(p))));self.assertFalse(c['consistent_over_union']);self.assertEqual(c['counts']['insufficient_evidence'],2)
    def test_same_block_payload_disagreement_is_not_silently_merged(self):
        from astra_pipeline.compare import compare
        a=self.value();p=self.root/'different-payload.sqlite';s=BlockStore(p,100,100)
        try:
            raw=json.loads(rich_block());raw['result']['blockTime']=123;s.apply(s.capture(100,s.session(context()),canonical(raw).encode()))
        finally:s.close()
        c=compare(a,enrich(bundle(capture_source(p))));self.assertEqual(c['counts']['payload_disagreement'],1);self.assertFalse(c['consistent_over_union'])

    def test_native_transfer_not_reported_unsupported_by_combined_decoder(self):
        v=self.value(tx());self.assertEqual(v['payload']['metrics']['event_kinds'],{'sol_transfer':1});self.assertEqual(v['payload']['metrics']['unsupported_instructions'],0)

    def test_resume_pending_provenance_after_source_has_advanced(self):
        source=self.root/'advancing.sqlite';s=BlockStore(source,100,101)
        try:s.apply(s.capture(100,s.session(context()),rich_block(100,99)))
        finally:s.close()
        out=self.root/'advancing-output'
        def stop(stage):
            if stage=='captured':raise RuntimeError('interrupted')
        with self.assertRaises(RuntimeError):offline(source,out,stop)
        s=BlockStore(source)
        try:s.apply(s.capture(101,s.session(context()),rich_block(101,100)))
        finally:s.close()
        r=offline(source,out);self.assertEqual(r['status'],'PASS');self.assertEqual(r['provenance']['pending'],0);self.assertEqual(r['provenance']['datasets'],2);self.assertEqual(r['index']['unique_events'],6)
