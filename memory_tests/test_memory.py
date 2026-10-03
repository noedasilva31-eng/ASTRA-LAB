import copy,json,os,sqlite3,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_memory.decode import ALPHABET,SYSTEM,b58decode,decode_block
from astra_memory.store import Memory,rebuild
from astra_memory.import_blocks import import_blocks
from astra_blocks.rpc import canonical,digest
from astra_blocks.store import BlockStore
from block_tests.test_blocks import context,block
ROOT=Path(__file__).resolve().parents[1]

def b58(raw):
    value=int.from_bytes(raw,'big');s=''
    while value:value,rem=divmod(value,58);s=ALPHABET[rem]+s
    return '1'*(len(raw)-len(raw.lstrip(b'\0')))+s
A=b58(bytes([1])*32);B=b58(bytes([2])*32);OTHER=b58(bytes([3])*32)
def tx(version='legacy',amount=123):
    return {'version':version,'transaction':{'signatures':[b58(bytes([9])*64)],'message':{
        'accountKeys':[A,B,SYSTEM],'instructions':[{'programIdIndex':2,'accounts':[0,1],
        'data':b58(struct.pack('<IQ',2,amount))}]}},'meta':{'err':None,'innerInstructions':[]}}
def raw_block(transactions=None):
    value=json.loads(block(100,99));value['result']['transactions']=[tx()] if transactions is None else transactions
    return canonical(value).encode()
class MemoryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'m.sqlite';self.m=Memory(self.path)
    def tearDown(self):self.m.close();self.tmp.cleanup()
    def ingest(self,raw=None):
        ident=self.m.capture('block100',100,raw or raw_block(),context());self.m.publish(ident);return ident
    def test_legacy_exact_transfer(self):
        d=decode_block(100,raw_block(),context());self.assertEqual(len(d['events']),1)
        e=d['events'][0];self.assertEqual((e['source'],e['destination'],e['lamports']),(A,B,'123'))
        self.assertTrue(d['coverage']['fully_decoded'])
    def test_v0_loaded_addresses(self):
        t=tx(0);t['transaction']['message']['accountKeys']=[A,SYSTEM]
        t['transaction']['message']['addressTableLookups']=[{'accountKey':OTHER}]
        t['meta']['loadedAddresses']={'writable':[B],'readonly':[]}
        t['transaction']['message']['instructions'][0].update(programIdIndex=1,accounts=[0,2])
        d=decode_block(100,raw_block([t]),context());self.assertEqual(d['events'][0]['destination'],B)
    def test_v1_and_u64_precision(self):
        d=decode_block(100,raw_block([tx(1,2**64-1)]),context());self.assertEqual(d['events'][0]['lamports'],str(2**64-1))
    def test_failed_transaction_no_transfer(self):
        t=tx();t['meta']['err']={'InstructionError':[0,'Custom']}
        d=decode_block(100,raw_block([t]),context());self.assertEqual(d['events'],[]);self.assertEqual(d['coverage']['transactions']['failed'],1)
    def test_unknown_program_explicit(self):
        t=tx();t['transaction']['message']['accountKeys'][2]=OTHER
        d=decode_block(100,raw_block([t]),context());self.assertEqual(d['events'],[]);self.assertEqual(d['coverage']['instructions']['unsupported'],1)
    def test_wrong_opcode_not_transfer(self):
        t=tx();t['transaction']['message']['instructions'][0]['data']=b58(struct.pack('<IQ',11,12))
        self.assertEqual(decode_block(100,raw_block([t]),context())['events'],[])
    def test_inner_instruction_not_assumed_successful(self):
        t=tx();ix=copy.deepcopy(t['transaction']['message']['instructions'][0]);t['meta']['innerInstructions']=[{'index':0,'instructions':[ix]}]
        d=decode_block(100,raw_block([t]),context());self.assertEqual(len(d['events']),1)
        self.assertEqual(d['coverage']['instructions']['unsupported'],1)
    def test_missing_meta_and_unknown_version_accounted(self):
        a=tx();a['meta']=None;b=tx(9)
        d=decode_block(100,raw_block([a,b]),context());self.assertEqual(d['events'],[])
        self.assertEqual(d['coverage']['transactions'],{'processed':0,'failed':0,'unsupported':1,'error':1})
        self.assertTrue(d['coverage']['accounting_ok'])
    def test_invalid_indexes_and_data_never_publish(self):
        for change in ({'accounts':[0,99]},{'programIdIndex':False},{'data':'0'},{'data':b58(struct.pack('<I',2))}):
            t=tx();t['transaction']['message']['instructions'][0].update(change)
            d=decode_block(100,raw_block([t]),context());self.assertEqual(d['events'],[]);self.assertEqual(d['coverage']['instructions']['error'],1)
    def test_missing_loaded_accounts_fail_closed(self):
        t=tx(0);t['transaction']['message']['addressTableLookups']=[{}]
        self.assertEqual(decode_block(100,raw_block([t]),context())['coverage']['transactions']['error'],1)
    def test_pending_recovery_and_dedup(self):
        ident=self.m.capture('block100',100,raw_block(),context());self.assertEqual(self.m.audit()['pending'],1)
        self.m.close();self.m=Memory(self.path);self.m.recover();before=self.m.dataset()
        self.assertEqual(self.ingest(),ident);self.m.recover();self.assertEqual(before,self.m.dataset())
        self.assertEqual(self.m.audit()['events'],1)
    def test_source_conflict_preserves_original(self):
        self.ingest();before=self.m.dataset()
        with self.assertRaises(ValueError):self.m.capture('block100',100,raw_block([tx(amount=124)]),context())
        self.assertEqual(before,self.m.dataset())
    def test_raw_corruption_detected(self):
        ident=self.ingest();self.m.db.execute('DROP TRIGGER no_UPDATE_memory_inputs');self.m.db.execute("UPDATE memory_inputs SET raw=?",(b'bad',));self.m.db.commit()
        self.assertFalse(self.m.audit()['healthy'])
        with self.assertRaises(ValueError):self.m.replay(ident)
    def test_publication_corruption_detected(self):
        self.ingest();self.m.db.execute('DROP TRIGGER no_UPDATE_memory_events');self.m.db.execute("UPDATE memory_events SET document='{}'");self.m.db.commit()
        self.assertFalse(self.m.audit()['healthy'])
    def test_export_rebuild_same_dataset(self):
        self.ingest();archive=Path(self.tmp.name)/'dataset.json';self.m.export(archive);dest=Path(self.tmp.name)/'restored.sqlite'
        self.assertTrue(rebuild(archive,dest)['healthy']);other=Memory(dest)
        try:self.assertEqual(other.dataset(),self.m.dataset())
        finally:other.close()
        with self.assertRaises(ValueError):rebuild(archive,dest)
    def test_export_manifest_tamper_rejected(self):
        self.ingest();archive=Path(self.tmp.name)/'dataset.json';self.m.export(archive)
        obj=json.loads(archive.read_text());obj['payload']['records'][0]['slot']=101;archive.write_text(json.dumps(obj))
        with self.assertRaises(ValueError):rebuild(archive,Path(self.tmp.name)/'bad.sqlite')
    def test_import_blocks_read_only_and_repeatable(self):
        path=Path(self.tmp.name)/'blocks.sqlite';s=BlockStore(path,100,100)
        sid=s.session(context());s.apply(s.capture(100,sid,raw_block()));s.close();before=path.read_bytes()
        import_blocks(path,self.m);import_blocks(path,self.m)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.m.audit()['events'],1)
    def test_crash_before_and_after_publication(self):
        for phase in ('captured','published'):
            path=Path(self.tmp.name)/(phase+'.sqlite')
            code="from astra_memory.store import Memory\nfrom memory_tests.test_memory import raw_block,context\nimport os,sys\nm=Memory(sys.argv[1]);i=m.capture('block100',100,raw_block(),context())\nif sys.argv[2]=='published':m.publish(i)\nos._exit(73)"
            p=subprocess.run([sys.executable,'-B','-c',code,str(path),phase],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10);self.assertEqual(p.returncode,73)
            m=Memory(path)
            try:m.recover();m.recover();self.assertEqual(m.audit()['events'],1);self.assertTrue(m.audit()['healthy'])
            finally:m.close()
    def test_metadata_corruption_detected(self):
        self.ingest();self.m.db.execute('DROP TRIGGER no_UPDATE_memory_inputs')
        self.m.db.execute("UPDATE memory_inputs SET source_key='wrong'");self.m.db.commit()
        self.assertFalse(self.m.audit()['healthy'])
    def test_rebuild_failure_leaves_no_destination(self):
        self.ingest();archive=Path(self.tmp.name)/'dataset.json';self.m.export(archive)
        obj=json.loads(archive.read_text());obj['payload']['records'][0]['decoded_hash']='wrong'
        obj['dataset_sha256']=digest(canonical(obj['payload']).encode());archive.write_text(json.dumps(obj))
        dest=Path(self.tmp.name)/'bad.sqlite'
        with self.assertRaises(ValueError):rebuild(archive,dest)
        self.assertFalse(dest.exists())
    def test_publication_transaction_rollback(self):
        ident=self.m.capture('block100',100,raw_block(),context())
        self.m.db.execute("CREATE TRIGGER test_abort BEFORE INSERT ON memory_events BEGIN SELECT RAISE(ABORT,'test'); END")
        self.m.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):self.m.publish(ident)
        self.assertEqual(self.m.audit()['pending'],1)
        self.assertEqual(self.m.db.execute('SELECT COUNT(*) FROM memory_decoded').fetchone()[0],0)
        self.m.db.execute('DROP TRIGGER test_abort');self.m.db.commit()
        self.assertTrue(self.m.recover()['healthy']);self.assertEqual(self.m.audit()['events'],1)
    def test_foreign_database_refused_without_change(self):
        path=Path(self.tmp.name)/'foreign.sqlite';db=sqlite3.connect(path)
        try:db.execute('CREATE TABLE sentinel(value TEXT)');db.commit()
        finally:db.close()
        before=path.read_bytes()
        with self.assertRaises(ValueError):Memory(path)
        self.assertEqual(before,path.read_bytes())
    def test_missing_inner_coverage_explicit(self):
        t=tx();del t['meta']['innerInstructions']
        d=decode_block(100,raw_block([t]),context())
        self.assertEqual(len(d['events']),1);self.assertFalse(d['coverage']['fully_decoded'])
        self.assertEqual(d['coverage']['inner_coverage_unavailable'],1)
    def test_decoder_code_mismatch_rejected(self):
        self.ingest();archive=Path(self.tmp.name)/'dataset.json';self.m.export(archive)
        obj=json.loads(archive.read_text());obj['payload']['code_sha256']['decoder']='different'
        obj['dataset_sha256']=digest(canonical(obj['payload']).encode());archive.write_text(json.dumps(obj))
        with self.assertRaises(ValueError):rebuild(archive,Path(self.tmp.name)/'wrong-version.sqlite')
    def test_wrong_cluster_never_publishes(self):
        ctx=context();ctx['network']='solana-mainnet'
        ident=self.m.capture('block100',100,raw_block(),ctx)
        with self.assertRaises(ValueError):self.m.publish(ident)
        self.assertEqual(self.m.audit()['events'],0);self.assertEqual(self.m.audit()['pending'],1)
    def test_append_only(self):
        self.ingest()
        for table in ('memory_inputs','memory_decoded','memory_events'):
            with self.assertRaises(sqlite3.IntegrityError):self.m.db.execute('DELETE FROM '+table)
            self.m.db.rollback()
if __name__=='__main__':unittest.main()
