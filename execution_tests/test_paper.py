import copy,json,tempfile,unittest
from pathlib import Path
from astra_execution.paper import Paper,Model,replay_rows
from astra_execution.quotes import quote
from astra_observer.spine import Archive,NETWORKS,canonical
from astra_observer.risk import Policy
from observer_tests.test_observer import response
from memory_tests.test_memory import A,B
class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.a=Archive(self.root/'raw','mainnet');self.a.append('rpc',response(NETWORKS['mainnet']),{'method':'getGenesisHash'},observed_ns=1);self.p=Paper(self.root/'paper',A,initial=10000,policy=Policy(max_position=5000,min_liquidity=1),model=Model(fee_quote_raw=10,adverse_bps=0),archive=self.a)
    def tearDown(self):self.p.close();self.a.close();self.tmp.cleanup()
    def q(self,side='BUY',amount=1000,output=2000,slot=101,at=5):
        x,y=(A,B) if side=='BUY' else (B,A);v={'inputMint':x,'outputMint':y,'inAmount':str(amount),'outAmount':str(output),'otherAmountThreshold':str(output),'swapMode':'ExactIn','slippageBps':0,'priceImpactPct':'0.001','contextSlot':slot,'routePlan':[{'swapInfo':{'label':'fixture'}}]};return self.a.append('quote',canonical(v).encode(),{'provider':'jupiter-v1','request':{'inputMint':x,'outputMint':y,'amount':amount,'slippageBps':0}},observed_ns=at)
    def opportunity(self,seq,amount=1000,slot=100,at=10):
        return {'slot':slot,'availability_ns':at,'heartbeat_ns':at,'coverage':'OBSERVED','data_health':'OBSERVED','authority_state':'OBSERVED_SAFE','execution_quote':{'status':'OBSERVED','exit_possible':True,'provenance':quote(self.a,seq)['provenance'],'size_raw':amount,'liquidity_quote_raw':100000,'slippage_bps':0,'observed_ns':quote(self.a,seq)['observed_ns'],'expires_ns':at+1000},'fixture_only':True}
    def buy(self):
        before=self.q(slot=100,at=5);op=self.opportunity(before);r=self.p.submit('buy','BUY',B,1000,op,10);self.assertEqual(r['kind'],'intent');later=self.q(at=20);return self.p.settle(self.a,'buy',later,self.opportunity(later,slot=101,at=20),20)
    def test_roundtrip_portfolio_pnl_exact(self):
        self.buy();self.assertEqual(self.p.state()['cash_quote_raw'],8990);before=self.q('SELL',2000,1200,slot=102,at=30);self.p.submit('sell','SELL',B,2000,self.opportunity(before,2000,102,30),30);later=self.q('SELL',2000,1200,slot=103,at=40);self.p.settle(self.a,'sell',later,self.opportunity(later,2000,103,40),40);s=self.p.state();self.assertEqual(s['cash_quote_raw'],10180);self.assertEqual(s['realized_scenario_pnl_quote_raw'],180);self.assertEqual(s['positions'],{})
    def test_actual_observatory_partial_state_rejected(self):
        q=self.q();op=self.opportunity(q);op['coverage']='PARTIAL';r=self.p.submit('x','BUY',B,1000,op,10);self.assertEqual(r['kind'],'reject');self.assertEqual(self.p.state()['cash_quote_raw'],10000)
    def test_intent_and_settlement_idempotence(self):
        q=self.q();op=self.opportunity(q);a=self.p.submit('x','BUY',B,1000,op,10);self.assertEqual(a,self.p.submit('x','BUY',B,1000,op,10));q=self.q(at=20);result=self.p.settle(self.a,'x',q,self.opportunity(q,slot=101,at=20),20);self.assertEqual(result,self.p.settle(self.a,'x',q,self.opportunity(q,slot=101,at=20),20));self.assertEqual(self.p.state()['sequence'],2)
    def test_same_slot_cannot_fill(self):
        q=self.q(slot=100);op=self.opportunity(q);self.p.submit('x','BUY',B,1000,op,10)
        with self.assertRaisesRegex(ValueError,'quote_not_after'):self.p.settle(self.a,'x',q,self.opportunity(q,at=20),20)
    def test_quote_from_future_rejected(self):
        q=self.q();self.p.submit('x','BUY',B,1000,self.opportunity(q),10);q=self.q(at=30)
        with self.assertRaisesRegex(ValueError,'expired_or_future'):self.p.settle(self.a,'x',q,self.opportunity(q,at=20),20)
    def test_kill_switch_rechecked_at_settlement(self):
        q=self.q();self.p.submit('x','BUY',B,1000,self.opportunity(q),10);q=self.q(at=20)
        with self.assertRaisesRegex(ValueError,'risk_rejected'):self.p.settle(self.a,'x',q,self.opportunity(q,at=20),20,kill=True)
        self.assertEqual(self.p.state()['cash_quote_raw'],10000)
    def test_rollback_after_calculation(self):
        q=self.q();self.p.submit('x','BUY',B,1000,self.opportunity(q),10);q=self.q(at=20)
        def stop():raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):self.p.settle(self.a,'x',q,self.opportunity(q,at=20),20,hook=stop)
        self.assertEqual(self.p.state()['cash_quote_raw'],10000);self.assertIn('x',self.p.state()['pending'])
    def test_corruption_fail_closed(self):
        self.buy();self.p.db.execute('DROP TRIGGER no_UPDATE_ledger');self.p.db.execute("UPDATE ledger SET doc='{}' WHERE seq=1");self.p.db.commit()
        with self.assertRaisesRegex(ValueError,'chain_mismatch'):self.p.state()
    def test_model_immutable(self):
        with self.assertRaisesRegex(ValueError,'immutable_paper_configuration'):Paper(self.root/'paper',A,model=Model(delay_slots=3))
    def test_explicit_cancel_releases_pending(self):
        q=self.q();self.p.submit('x','BUY',B,1000,self.opportunity(q),10);self.p.cancel('x');self.assertFalse(self.p.state()['pending'])
    def test_quote_bound_to_request(self):
        seq=self.q();f,h=self.a.frame(seq);import base64
        v=json.loads(base64.b64decode(f['raw']));v['inAmount']='2';seq=self.a.append('quote',canonical(v).encode(),f['metadata'])
        with self.assertRaisesRegex(ValueError,'amount_mismatch'):quote(self.a,seq)
    def test_quote_requires_genesis(self):
        other=Archive(self.root/'other','mainnet')
        try:
            f,_=self.a.frame(self.q());import base64
            seq=other.append('quote',base64.b64decode(f['raw']),f['metadata'])
            with self.assertRaisesRegex(ValueError,'identity_unproven'):quote(other,seq)
        finally:other.close()
    def test_state_replay_exact(self):
        self.buy();self.assertEqual(self.p.state(),replay_rows(self.p.rows(),10000))
    def test_wrong_quote_size_cannot_settle(self):
        q=self.q();self.p.submit('x','BUY',B,1000,self.opportunity(q),10);bad=self.q(amount=999,at=20)
        with self.assertRaisesRegex(ValueError,'direction_or_size'):self.p.settle(self.a,'x',bad,self.opportunity(bad,at=20),20)
    def test_decision_cannot_use_future_quote(self):
        q=self.q(at=20)
        with self.assertRaisesRegex(ValueError,'decision_quote_from_future'):self.p.submit('x','BUY',B,1000,self.opportunity(q),10)
        self.assertEqual(self.p.state()['sequence'],0)
    def test_existing_unrelated_database_untouched(self):
        import sqlite3
        path=self.root/'unrelated';db=sqlite3.connect(path);db.execute('CREATE TABLE reference(x)');db.commit();db.close();before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'foreign_database'):Paper(path,A)
        self.assertEqual(path.read_bytes(),before)
    def test_reopen_and_cli_audit(self):
        import subprocess,sys
        self.buy();expected=self.p.state();self.p.close();self.p=Paper(self.root/'paper',A,initial=10000,policy=Policy(max_position=5000,min_liquidity=1),model=Model(fee_quote_raw=10,adverse_bps=0),archive=self.a);self.assertEqual(expected,self.p.state())
        p=subprocess.run([sys.executable,'-B','-m','astra_execution','--ledger',str(self.root/'paper'),'--output',str(self.root/'audit.json')],capture_output=True,timeout=20);self.assertEqual(p.returncode,0);self.assertEqual(json.loads((self.root/'audit.json').read_text())['state'],expected)
    def test_adverse_model_cannot_bypass_slippage_limit(self):
        with self.assertRaisesRegex(ValueError,'model_slippage_exceeds_risk'):Paper(self.root/'stress',A,model=Model(adverse_bps=101))
    def test_entry_fees_count_against_position_cap(self):
        q=self.q(amount=5000);r=self.p.submit('x','BUY',B,5000,self.opportunity(q,amount=5000),10);self.assertEqual(r['kind'],'reject');self.assertIn('cost_including_fee_limit',r['risk']['reasons'])
