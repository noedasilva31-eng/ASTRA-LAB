import base64,hashlib,json,os,socket,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.rpc import canonical,DEVNET_GENESIS,normalize
from astra_blocks.store import BlockStore
ROOT=Path(__file__).resolve().parents[1]
def response(value):return canonical({'jsonrpc':'2.0','id':1,'result':value}).encode()
def error(code):return canonical({'jsonrpc':'2.0','id':1,'error':{'code':code,'message':'synthetic'}}).encode()
def block(slot,parent):return response({'blockhash':'B'+str(slot),'previousBlockhash':'B'+str(parent),'parentSlot':parent,'blockHeight':slot,'blockTime':None,'transactions':[]})
def context():return {'origin':'https://fixture.invalid','network':'solana-devnet','commitment':'finalized','genesis_raw':base64.b64encode(response(DEVNET_GENESIS)).decode(),'tip_raw':base64.b64encode(response(200)).decode()}
class Fixture:
    def __init__(self,repaired=False):self.calls=[];self.repaired=repaired
    def context(self):return context()
    def block(self,slot):
        self.calls.append(slot)
        if slot==101:return error(-32007),None
        if slot==103 and not self.repaired:return response(None),None
        if slot==104 and not self.repaired:return error(-32603),None
        return block(slot,100 if slot==102 else slot-1),None
class BlockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'blocks.sqlite';self.s=BlockStore(self.path,100,105)
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('offline_test_network'));self.network.start()
    def tearDown(self):self.network.stop();self.s.close();self.tmp.cleanup()
    def test_states_checkpoint_retry(self):
        c=Fixture();self.assertEqual(self.s.collect(c,max_slots=3)['next_slot'],103)
        self.s.close();self.s=BlockStore(self.path);a=self.s.collect(c)
        self.assertEqual(c.calls,list(range(100,106)))
        self.assertEqual(a['counts'],{'archived':3,'skipped':1,'unavailable':1,'error':1});self.assertTrue(a['healthy'])
        pub=list(self.s.db.execute('SELECT * FROM publications'));self.s.recover();self.s.recover();self.s.collect(c)
        self.assertEqual(pub,list(self.s.db.execute('SELECT * FROM publications')))
        c=Fixture(True);a=self.s.collect(c,retry=True)
        self.assertEqual(c.calls,[103,104]);self.assertEqual(a['publications'],5);self.assertEqual(a['unresolved'],0);self.assertTrue(a['healthy'])
    def test_ambiguous_errors_never_skipped(self):
        for code in (-32001,-32004,-32007,-32009,-32014):self.assertEqual(normalize(101,error(code),None,context())[0],'unavailable')
        self.assertEqual(normalize(101,response(None),None,context())[0],'unavailable')
    def test_raw_replay_recovery(self):
        sid=self.s.session(context());raw=block(100,99);ident=self.s.capture(100,sid,raw)
        self.assertEqual(self.s.db.execute('SELECT raw FROM attempts').fetchone()[0],raw);self.assertEqual(self.s.audit()['pending_attempts'],1)
        self.s.recover();p=self.s.replay(ident);self.assertEqual(p['document_hash'],hashlib.sha256(p['document'].encode()).hexdigest());self.assertTrue(self.s.audit()['healthy'])
    def test_hard_crash(self):
        for stage in ('captured','committed'):
            path=Path(self.tmp.name)/(stage+'.sqlite')
            script="import os,sys\nfrom block_tests.test_blocks import Fixture\nfrom astra_blocks.store import BlockStore\ns=BlockStore(sys.argv[1],100,105)\ndef crash(stage,ident):\n if stage==sys.argv[2]:os._exit(73)\ns.collect(Fixture(),hook=crash)\n"
            p=subprocess.run([sys.executable,'-B','-c',script,str(path),stage],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            self.assertEqual(p.returncode,73);other=BlockStore(path)
            try:
                other.recover();self.assertEqual(other.meta()['next_slot'],101);other.collect(Fixture())
                before=list(other.db.execute('SELECT * FROM publications'));other.recover();other.collect(Fixture())
                self.assertEqual(before,list(other.db.execute('SELECT * FROM publications')));self.assertEqual(len(before),3);self.assertTrue(other.audit()['healthy'])
            finally:other.close()
    def test_redelivery(self):
        sid=self.s.session(context())
        for _ in range(2):self.s.apply(self.s.capture(100,sid,block(100,99)))
        self.assertEqual(self.s.audit()['publications'],1)
    def test_conflict_halts(self):
        sid=self.s.session(context());self.s.apply(self.s.capture(100,sid,block(100,99)));obj=json.loads(block(100,99));obj['result']['blockhash']='conflict'
        ident=self.s.capture(100,sid,canonical(obj).encode())
        with self.assertRaises(ValueError):self.s.apply(ident)
        self.assertEqual(self.s.audit()['publications'],1);self.assertEqual(self.s.audit()['pending_attempts'],1)
    def test_parent_hash_required(self):
        sid=self.s.session(context());self.s.apply(self.s.capture(100,sid,block(100,99)));obj=json.loads(block(102,100));obj['result']['previousBlockhash']='wrong'
        ident=self.s.capture(102,sid,canonical(obj).encode())
        with self.assertRaises(ValueError):self.s.apply(ident)
        self.assertNotEqual(self.s.audit()['slots'][1]['status'],'skipped')
    def test_parent_absent_not_skipped(self):
        sid=self.s.session(context());self.s.apply(self.s.capture(102,sid,block(102,99)));self.assertEqual(self.s.audit()['counts']['skipped'],0)
    def test_transport_timeout(self):
        sid=self.s.session(context());self.s.apply(self.s.capture(100,sid,None,'timeout'));a=self.s.audit()
        self.assertEqual(a['slots'][0]['reason'],'timeout');self.assertEqual(a['next_slot'],101);self.assertEqual(a['publications'],0);self.assertTrue(a['healthy'])
    def test_raw_corruption(self):
        self.s.collect(Fixture(),max_slots=1);self.s.db.execute('DROP TRIGGER no_UPDATE_attempts');self.s.db.execute('UPDATE attempts SET raw=?',(b'bad',));self.s.db.commit()
        self.assertGreater(self.s.audit()['hash_or_replay_errors'],0)
        with self.assertRaises(ValueError):self.s.replay(1)
    def test_document_corruption(self):
        self.s.collect(Fixture(),max_slots=1);self.s.db.execute('DROP TRIGGER no_UPDATE_publications');self.s.db.execute("UPDATE publications SET document='{}'");self.s.db.commit();self.assertFalse(self.s.audit()['healthy'])
    def test_checkpoint_corruption(self):
        self.s.db.execute('UPDATE block_meta SET next_slot=106');self.s.db.commit();self.assertFalse(self.s.audit()['checkpoint_ok'])
    def test_wrong_cluster_future_range(self):
        ctx=context();ctx['genesis_raw']=base64.b64encode(response('wrong')).decode()
        with self.assertRaises(ValueError):self.s.session(ctx)
        ctx=context();ctx['tip_raw']=base64.b64encode(response(102)).decode()
        with self.assertRaises(ValueError):self.s.session(ctx)
    def test_refuse_reference_db(self):
        path=Path(self.tmp.name)/'reference.sqlite';c=sqlite3.connect(path);c.execute('CREATE TABLE example(x)');c.commit();c.close();before=path.read_bytes()
        with self.assertRaises(ValueError):BlockStore(path,100,105)
        self.assertEqual(path.read_bytes(),before)
    def test_error_text_not_logged(self):
        raw=b'{"jsonrpc":"2.0","id":1,"error":{"code":-32603,"message":"SYNTHETIC_SECRET"}}'
        self.assertNotIn('SYNTHETIC_SECRET',str(normalize(100,raw,None,context())))
    def test_live_worker_protocol_with_simulated_transport(self):
        # Exercise the exact live phase orchestration, explicitly simulated.
        from block_validation import run
        folder=Path(self.tmp.name)/'protocol';folder.mkdir()
        with patch.object(run,'Rpc',return_value=Fixture()):
            for phase in ('first','resume','retry','offline_replay'):
                run.worker(phase,folder)
                result=json.loads((folder/(phase+'.json')).read_text())
                self.assertEqual(result['status'],'PASS',phase)
        evidence=result['evidence']
        self.assertEqual(evidence['expected_slots'],6)
        self.assertEqual(evidence['publications'],6)
        self.assertTrue(evidence['first_pass_complete'])
    def test_session_hash_corruption(self):
        self.s.session(context())
        self.s.db.execute('DROP TRIGGER no_UPDATE_sessions')
        self.s.db.execute("UPDATE sessions SET hash='wrong'");self.s.db.commit()
        self.assertFalse(self.s.audit()['healthy'])
    def test_state_corruption_detected(self):
        self.s.collect(Fixture(),max_slots=1)
        self.s.db.execute("UPDATE slots SET status='error' WHERE slot=100");self.s.db.commit()
        self.assertFalse(self.s.audit()['healthy'])
    def test_missing_slot_detected(self):
        self.s.db.execute('DELETE FROM slots WHERE slot=103');self.s.db.commit()
        self.assertFalse(self.s.audit()['accounting_ok'])
    def test_corrupt_checkpoint_blocks_network_collection(self):
        self.s.db.execute('UPDATE block_meta SET next_slot=106');self.s.db.commit()
        fixture=Fixture()
        with self.assertRaises(ValueError):self.s.collect(fixture)
        self.assertEqual(fixture.calls,[])
    def test_history_survives_retry(self):
        self.s.collect(Fixture())
        before=[tuple(r) for r in self.s.db.execute('SELECT * FROM attempts ORDER BY id')]
        self.s.collect(Fixture(True),retry=True)
        after=[tuple(r) for r in self.s.db.execute('SELECT * FROM attempts ORDER BY id')]
        self.assertEqual(after[:len(before)],before)
        self.assertEqual(len(after),8)
        audit=self.s.audit()
        self.assertEqual(audit['coverage']['attempted_slots'],6)
        self.assertEqual(audit['coverage']['resolved_fraction'],1)
    def test_append_only(self):
        self.s.collect(Fixture(),max_slots=1)
        for table in ('sessions','attempts','outcomes','publications'):
            with self.assertRaises(sqlite3.IntegrityError):self.s.db.execute('DELETE FROM '+table)
            self.s.db.rollback()
if __name__=='__main__':unittest.main()
