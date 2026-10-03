import unittest,tempfile,hashlib,json,subprocess,sys
from pathlib import Path
from astra_position.audit import audit
from astra_position.resume import prepare
from astra_position.runtime import PositionBridge
from astra_observer.spine import Archive
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT/'position_reference/all-validation-jyqge_an/context-proofs'
class ReferenceTests(unittest.TestCase):
    def test_actual_position_replay_freeze_and_separate_failures(self):
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file()}
        r=audit(SOURCE);p=r['portfolio'];self.assertEqual(r['audit']['status'],'PASS');self.assertEqual(r['audit']['plans'],51);self.assertEqual(p['sequence'],2);self.assertEqual(p['cash_quote_raw'],987900000)
        pos=next(iter(p['positions'].values()));self.assertEqual(pos['units'],4624230);self.assertEqual(pos['cost'],12100000);self.assertEqual(r['entry']['availability_ns'],1790953857333198100)
        self.assertTrue(r['original_freeze_verifications']);self.assertTrue(all(x['status']=='PASS' for x in r['original_freeze_verifications']));self.assertEqual(r['original_budget']['used'],188)
        self.assertIn('devnet_identity_not_verified',[x['code'] for x in r['separate_historical_failures']]);self.assertTrue(r['retrospective_position_health'])
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*') if p.is_file()})
    def test_actual_resume_new_process_no_double_buy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'session';m=prepare(SOURCE,root);again=prepare(SOURCE,root);self.assertEqual(m,again)
            script="from pathlib import Path;import sys;from astra_observer.spine import Archive;from astra_position.runtime import PositionBridge;p=Path(sys.argv[1]);a=Archive(p/'raw.sqlite','mainnet');b=PositionBridge(a,p/'state');before=b.paper.state();b.recover();b.recover();assert b.paper.state()==before;assert before['sequence']==2;assert b.verify_replay()['status']=='PASS';b.close();a.close()"
            r=subprocess.run([sys.executable,'-B','-c',script,str(root)],capture_output=True,timeout=60);self.assertEqual(r.returncode,0,r.stderr.decode('utf-8'))
            a=Archive(root/'raw.sqlite','mainnet')
            try:self.assertEqual(a.db.execute('SELECT used FROM rpc_budget').fetchone()[0],0);self.assertEqual(a.db.execute('SELECT used FROM position_parent_rpc_budget').fetchone()[0],188)
            finally:a.close()
