import copy,json,struct,tempfile,unittest
from pathlib import Path
from astra_dex import pumpswap as p
from astra_dex.decode import decode
from astra_blocks.store import BlockStore
from astra_blocks.rpc import canonical
from astra_pipeline.decode import enrich
from astra_pipeline.run import offline
from astra_provenance.archive import bundle,capture_source
from astra_timeline.store import Timeline
from block_tests.test_blocks import context
from pipeline_tests.test_pipeline import rich_block
from memory_tests.test_memory import tx,b58

def fixture(name='buy'):
    spec=p.SCHEMA['instructions'][name];names=spec['accounts'];keys=[b58(bytes([i+1])*32) for i in range(len(names))]+[p.PROGRAM];program=len(keys)-1
    keys[names.index('program')]=p.PROGRAM
    accounts=dict(zip(names,keys));event=p.SCHEMA['events'][spec['event']];fields={};raw=bytearray(event['discriminator'])
    for f in event['fields']:
        key,typ=f['name'],f['type']
        if typ=='pubkey':value=accounts.get(key,keys[0]);raw.extend(p.b58decode(value))
        elif typ=='bool':value=False;raw.append(0)
        elif typ=='string':value=name;b=value.encode();raw.extend(struct.pack('<I',len(b))+b)
        else:
            value=-12 if typ=='i128' else 100;raw.extend(value.to_bytes(int(typ[1:])//8,'little',signed=typ.startswith('i')))
        fields[key]=value
    t=tx();t['transaction']['message']['accountKeys']=keys
    t['transaction']['message']['instructions']=[{'programIdIndex':program,'accounts':list(range(len(names))),'data':b58(bytes(spec['discriminator'])+b'\x00'*16)}]
    t['meta'].update(fee=5000,preTokenBalances=[],postTokenBalances=[],innerInstructions=[{'index':0,'instructions':[{'programIdIndex':program,'accounts':[names.index('event_authority')],'stackHeight':2,'data':b58(p.EVENT_TAG+raw)}]}])
    return t,fields

class DexTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def dataset(self,t):
        s=BlockStore(self.root/'source.sqlite',100,100)
        try:s.apply(s.capture(100,s.session(context()),rich_block(transaction=t)))
        finally:s.close()
        return enrich(bundle(capture_source(self.root/'source.sqlite')))
    def result(self,t):return decode(self.dataset(t))['payload']
    def test_buy_wallet_mints_amounts_fees_and_signed_reserves(self):
        t,fields=fixture();r=self.result(t);e=r['events'][0]['event'];self.assertEqual(e['fields']['virtual_quote_reserves'],'-12');self.assertEqual(e['input_amount_raw'],'100');self.assertEqual(e['kind'],'swap');self.assertEqual(e['wallet'],fields['user']);self.assertNotEqual(e['input_mint'],e['output_mint']);self.assertFalse(e['executable_quote']);self.assertTrue(r['events'][0]['provenance']['raw_sha256'])
    def test_all_six_supported_instructions(self):
        for name in p.SCHEMA['instructions']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as tmp:
                self.root=Path(tmp);t,_=fixture(name);r=self.result(t);self.assertEqual(len(r['events']),1);self.assertEqual(r['events'][0]['event']['instruction'],name)
    def test_wrong_emitter_not_decoded(self):
        t,_=fixture();t['meta']['innerInstructions'][0]['instructions'][0]['programIdIndex']=0;r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['metrics']['instruction_states']['unresolved'],1)
    def test_failed_transaction_no_swap(self):
        t,_=fixture();t['meta']['err']={'InstructionError':[0,'Custom']};self.assertEqual(self.result(t)['events'],[])
    def test_missing_event_remains_unresolved(self):
        t,_=fixture();t['meta']['innerInstructions']=None;r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['coverage'][0]['instructions'][0]['reason'],'matching_event_missing')
    def test_unknown_layout_is_error(self):
        t,_=fixture();i=t['meta']['innerInstructions'][0]['instructions'][0];i['data']=b58(p.b58decode(i['data'])+b'\x00');r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['metrics']['instruction_states']['error'],1)
    def test_wrong_user_account_is_error(self):
        t,_=fixture();keys=t['transaction']['message']['accountKeys'];keys[1]=b58(bytes([100])*32);r=self.result(t);self.assertEqual(r['metrics']['instruction_states']['error'],1)
    def test_stack_unknown_not_authenticated(self):
        t,_=fixture();t['meta']['innerInstructions'][0]['instructions'][0]['stackHeight']=None;r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['metrics']['instruction_states']['unresolved'],1)
    def test_duplicate_event_is_error(self):
        t,_=fixture();g=t['meta']['innerInstructions'][0]['instructions'];g.append(copy.deepcopy(g[0]));r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['metrics']['instruction_states']['error'],1)
    def test_routed_swap_explicitly_unsupported(self):
        t,_=fixture();t['transaction']['message']['instructions'][0]['programIdIndex']=0;r=self.result(t);self.assertEqual(r['events'],[]);self.assertEqual(r['coverage'][0]['instructions'][0]['reason'],'routed_protocol_not_supported')
    def test_replay_and_pipeline_timeline_integration(self):
        t,_=fixture();v=self.dataset(t);r=decode(v);self.assertEqual(r,decode(copy.deepcopy(v)));a=offline(self.root/'source.sqlite',self.root/'business');self.assertEqual(a['dex']['events'],1)
        timeline=Timeline(self.root/'business'/'timeline.sqlite')
        try:self.assertEqual(timeline.query(100,100)['payload']['slots'][0]['feature']['dex_events'],r['payload']['events'])
        finally:timeline.close()
    def test_truncation_and_noncanonical_bool_fail_closed(self):
        spec=p.SCHEMA['events']['DepositEvent']
        with self.assertRaises(ValueError):p.event(bytes(spec['discriminator']),spec)
        with self.assertRaises(ValueError):p.event(b'12345678\x02',{'discriminator':list(b'12345678'),'fields':[{'name':'x','type':'bool'}]})
    def test_corrupt_source_cannot_be_decoded(self):
        t,_=fixture();v=self.dataset(t);v['payload']['base']['payload']['archive']['tables']['publications'][0]['document']='{}'
        with self.assertRaises(ValueError):decode(v)
