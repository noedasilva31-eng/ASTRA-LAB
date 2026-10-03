import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.rpc import Rpc,canonical
from astra_blocks.store import BlockStore
from block_tests.test_blocks import context,block,response
from memory_tests.test_memory import tx
from pipeline_tests.test_pipeline import factory,fake_call,rich_block
from validation_extensions.sol_probe import search
from memory_validation.run import decode_dataset
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'original.sqlite';s=BlockStore(self.source,100,100)
        try:s.apply(s.capture(100,s.session(context()),block(100,99)))
        finally:s.close()
    def tearDown(self):self.tmp.cleanup()
    def test_empty_initial_range_then_real_format_proof_replayed(self):
        def rpc(client,method,params):
            if method!='getBlock':return fake_call(client,method,params)
            slot=params[0]
            return (rich_block(slot,slot-1,tx()) if slot==98 else response(None)),None
        with patch.object(Rpc,'call',rpc):r=search(self.source,self.root, factory,max_slots=4)
        self.assertEqual(r['status'],'PASS');self.assertEqual(r['evidence']['searched_slots'],2);self.assertEqual(r['evidence']['selected_slot'],98)
        self.assertEqual(decode_dataset(self.root,self.root/'proof.sqlite')['final']['events'],1)
    def test_absence_remains_fail_and_budget_bounded(self):
        with patch.object(Rpc,'call',fake_call):r=search(self.source,self.root,factory,max_slots=3)
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['code'],'sol_probe_exhausted');self.assertEqual(r['evidence']['searched_slots'],3);self.assertEqual(r['evidence']['quota']['requests'],5)
    def test_deadline_not_pass(self):
        times=iter((0,20))
        with patch.object(Rpc,'call',fake_call):r=search(self.source,self.root,factory,max_slots=3,seconds=10,clock=lambda:next(times))
        self.assertEqual(r['status'],'FAIL');self.assertEqual(r['evidence']['searched_slots'],0)
    def test_existing_proof_needs_no_extra_request(self):
        p=self.root/'available.sqlite';s=BlockStore(p,100,100)
        try:s.apply(s.capture(100,s.session(context()),rich_block(100,99,tx())))
        finally:s.close()
        def forbidden(b):raise AssertionError('unexpected RPC')
        self.assertEqual(search(p,self.root,forbidden)['status'],'PASS')
    def test_original_source_unchanged(self):
        before=self.source.read_bytes()
        with patch.object(Rpc,'call',fake_call):search(self.source,self.root,factory,max_slots=1)
        self.assertEqual(self.source.read_bytes(),before)
