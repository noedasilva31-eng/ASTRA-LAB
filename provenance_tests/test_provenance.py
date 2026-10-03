import base64,copy,json,os,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical,digest
from block_tests.test_blocks import context,block,error,response
from memory_tests.test_memory import raw_block,tx,b58
from astra_provenance.archive import capture_source,bundle,verify
from astra_provenance.store import Journal,reconstruct
ROOT=Path(__file__).resolve().parents[1]
def fixture(path,partial=False):
    s=BlockStore(path,100,105);sid=s.session(context())
    for slot,parent in ((100,99),(102,100),(105,104)):
        if partial and slot!=100:continue
        obj=json.loads(block(slot,parent));t=tx(amount=slot);t['transaction']['signatures']=[b58(bytes([slot])*64)];obj['result']['transactions']=[t]
        s.apply(s.capture(slot,sid,canonical(obj).encode()))
    if not partial:
        for slot,raw in ((101,error(-32007)),(103,response(None)),(104,error(-32603))):s.apply(s.capture(slot,sid,raw))
    s.close()
class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'blocks.sqlite';fixture(self.source);self.a=capture_source(self.source)
    def tearDown(self):self.tmp.cleanup()
    def test_all_slots_accounted_incomplete_not_complete(self):
        c=bundle(self.a)['payload']['derived']['coverage'];self.assertEqual(c['counts'],dict(archived=3,skipped=1,unresolved=1,error=1,excluded=0));self.assertTrue(c['accounting_ok']);self.assertFalse(c['source_complete'])
    def test_provenance_every_event(self):
        b=bundle(self.a);d=b['payload']['derived'];self.assertEqual(len(d['events']),3)
        for x in d['events']:
            slot=x['event']['slot'];state=next(r for r in d['slots'] if r['slot']==slot)
            self.assertEqual(x['provenance']['raw_sha256'],state['publication']['raw_sha256']);self.assertEqual(x['provenance']['blockhash'],x['event']['blockhash'])
    def test_boundary_subset_preserves_external_skip_witnesses(self):
        a=capture_source(self.source,101,101);d=bundle(a)['payload']['derived'];self.assertEqual(d['coverage']['expected_slots'],1);self.assertTrue(d['coverage']['source_complete']);self.assertEqual(d['slots'][0]['skip_proof']['parent_slot'],100);self.assertEqual(d['slots'][0]['skip_proof']['child_slot'],102)
    def test_outside_boundaries_rejected(self):
        for start,end in ((99,102),(100,106),(105,100)):
            with self.assertRaises(ValueError):bundle(capture_source(self.source,start,end))
    def test_excluded_is_explicit(self):
        d=bundle(capture_source(self.source,100,102,[100]))['payload']['derived'];self.assertEqual(d['coverage']['counts']['excluded'],1);self.assertFalse(d['coverage']['included_range_complete']);self.assertEqual(len(d['events']),1);self.assertIsNotNone(d['slots'][0]['publication'])
    def test_cannot_exclude_unknown(self):
        with self.assertRaises(ValueError):bundle(capture_source(self.source,exclude=[103]))
    def test_never_attempted_explicit(self):
        p=self.root/'partial.sqlite';fixture(p,True);d=bundle(capture_source(p))['payload']['derived'];self.assertEqual(d['coverage']['counts']['unresolved'],5);self.assertEqual(d['slots'][1]['reason'],'not_attempted')
    def test_retry_preserves_error_and_previous_dataset(self):
        before=bundle(self.a);s=BlockStore(self.source)
        try:
            sid=s.session(context());s.apply(s.capture(104,sid,block(104,103)))
        finally:s.close()
        after=bundle(capture_source(self.source));state=after['payload']['derived']['slots'][4]
        self.assertEqual([a['status'] for a in state['attempts']],['error','archived']);self.assertEqual(before,bundle(self.a));self.assertNotEqual(before['dataset_sha256'],after['dataset_sha256'])
    def test_corrupt_raw_rejected(self):
        self.a['tables']['attempts'][0]['raw']=base64.b64encode(b'bad').decode()
        with self.assertRaises(ValueError):bundle(self.a)
    def test_missing_slot_rejected(self):
        self.a['tables']['slots'].pop()
        with self.assertRaises(ValueError):bundle(self.a)
    def test_missing_skip_witness_rejected(self):
        self.a['tables']['publications']=self.a['tables']['publications'][1:]
        with self.assertRaises(ValueError):bundle(self.a)
    def test_forged_complete_metric_rejected_even_with_new_outer_hash(self):
        b=bundle(self.a);b['payload']['derived']['coverage']['source_complete']=True;b['dataset_sha256']=digest(canonical(b['payload']).encode())
        with self.assertRaises(ValueError):verify(b)
    def test_forged_event_provenance_rejected(self):
        b=bundle(self.a);b['payload']['derived']['events'][0]['provenance']['slot']=104;b['dataset_sha256']=digest(canonical(b['payload']).encode())
        with self.assertRaises(ValueError):verify(b)
    def test_source_read_only(self):
        before=self.source.read_bytes();bundle(capture_source(self.source));self.assertEqual(before,self.source.read_bytes())
    def test_offline_reconstruction_exact(self):
        b=bundle(self.a);src=self.root/'dataset.json';src.write_text(canonical(b));dest=self.root/'reconstructed.json';reconstruct(src,dest);self.assertEqual(src.read_bytes(),dest.read_bytes())
        with self.assertRaises(FileExistsError):reconstruct(src,dest)
    def test_code_hash_mismatch_fail_closed(self):
        self.a['code_sha256']['decoder']='wrong'
        with self.assertRaises(ValueError):bundle(self.a)
    def test_journal_dedup_recover_no_republication(self):
        j=Journal(self.root/'j.sqlite')
        try:
            ident=j.capture(self.a);j.publish(ident);before=list(j.db.execute('SELECT * FROM provenance_events'));self.assertEqual(j.capture(self.a),ident);j.recover();j.recover();self.assertEqual(before,list(j.db.execute('SELECT * FROM provenance_events')));self.assertEqual(j.audit()['datasets'],1)
        finally:j.close()
    def test_crash_before_during_after_publication(self):
        src=self.root/'a.json';src.write_text(canonical(self.a))
        for phase in ('before','during','after'):
            path=self.root/(phase+'.sqlite')
            code="import json,os,sys\nfrom astra_provenance.store import Journal\nj=Journal(sys.argv[1]);i=j.capture(json.load(open(sys.argv[2])))\nif sys.argv[3]=='during':j.publish(i,hook=lambda:os._exit(73))\nif sys.argv[3]=='after':j.publish(i)\nos._exit(73)"
            p=subprocess.run([sys.executable,'-B','-c',code,str(path),str(src),phase],cwd=ROOT,timeout=20,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);self.assertEqual(p.returncode,73)
            j=Journal(path)
            try:j.recover();j.recover();self.assertTrue(j.audit()['healthy']);self.assertEqual(j.audit()['unique_event_publications'],3)
            finally:j.close()
    def test_pending_source_never_claimed_complete(self):
        s=BlockStore(self.source)
        try:s.capture(103,s.session(context()),block(103,102))
        finally:s.close()
        with self.assertRaises(ValueError):bundle(capture_source(self.source))
    def test_retry_new_version_preserves_old_and_unique_events(self):
        j=Journal(self.root/'versions.sqlite')
        try:
            old=j.publish(j.capture(self.a));old_doc=canonical(old)
            s=BlockStore(self.source)
            try:
                sid=s.session(context())
                for slot,parent in ((103,102),(104,103)):
                    obj=json.loads(block(slot,parent));t=tx(amount=slot);t['transaction']['signatures']=[b58(bytes([slot])*64)];obj['result']['transactions']=[t]
                    s.apply(s.capture(slot,sid,canonical(obj).encode()))
            finally:s.close()
            new=j.publish(j.capture(capture_source(self.source)));j.recover()
            self.assertEqual(j.audit()['datasets'],2);self.assertEqual(j.audit()['unique_event_publications'],5)
            self.assertTrue(new['payload']['derived']['coverage']['source_complete']);self.assertEqual(canonical(old),old_doc)
            self.assertEqual(j.db.execute('SELECT document FROM provenance_datasets WHERE capture_id=1').fetchone()[0],old_doc)
            self.assertEqual(len(new['payload']['derived']['slots'][4]['attempts']),2)
        finally:j.close()
    def test_journal_corruption_detected(self):
        j=Journal(self.root/'corrupt.sqlite')
        try:
            j.publish(j.capture(self.a));j.db.execute('DROP TRIGGER no_UPDATE_provenance_datasets');j.db.execute("UPDATE provenance_datasets SET document='{}'");j.db.commit()
            self.assertFalse(j.audit()['healthy'])
            with self.assertRaises(ValueError):j.export(1,self.root/'no.json')
        finally:j.close()
    def test_append_only(self):
        j=Journal(self.root/'append.sqlite')
        try:
            j.publish(j.capture(self.a))
            for table in ('provenance_captures','provenance_datasets','provenance_events'):
                with self.assertRaises(sqlite3.IntegrityError):j.db.execute('DELETE FROM '+table)
                j.db.rollback()
        finally:j.close()
    def test_foreign_database_refused(self):
        before=self.source.read_bytes()
        with self.assertRaises(ValueError):Journal(self.source)
        self.assertEqual(before,self.source.read_bytes())
    def test_bad_dataset_no_output(self):
        b=bundle(self.a);b['dataset_sha256']='bad';src=self.root/'bad.json';src.write_text(canonical(b));dest=self.root/'out.json'
        with self.assertRaises(ValueError):reconstruct(src,dest)
        self.assertFalse(dest.exists())
if __name__=='__main__':unittest.main()
