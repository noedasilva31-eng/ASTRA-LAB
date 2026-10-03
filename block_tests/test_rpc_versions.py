"""Regression tests derived from reported Windows -32015 failure; no remote access."""
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from astra_blocks.rpc import (Rpc,BLOCK_CONFIG,LEGACY_BLOCK_CONFIG,canonical,digest,
                             config_from_context,normalize,retry_metadata,error_diagnostic)
from astra_blocks.store import BlockStore
from block_tests.test_blocks import context,block,error,Fixture

ROOT=Path(__file__).resolve().parents[1]

def modern_context():
    ctx=context();ctx['block_config']=dict(BLOCK_CONFIG);return ctx

def versioned_block(slot,parent,version):
    value=json.loads(block(slot,parent))
    value['result']['transactions']=[{'version':version,'transaction':{'signatures':['fixture'],
        'message':{'accountKeys':['fixture'],'instructions':[],'recentBlockhash':'fixture',
                   'transactionConfig':{'computeUnitLimit':1000}}},'meta':{'err':None}}]
    return canonical(value).encode()

class VersionFixture(Fixture):
    def context(self):return modern_context()
    def block(self,slot):self.calls.append(slot);return versioned_block(slot,slot-1,1),None

class RpcVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.s=BlockStore(Path(self.tmp.name)/'b.sqlite',100,105)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def test_wire_request_integer_one_and_full_finalized(self):
        rpc=Rpc('https://fixture.invalid')
        class Transport:
            def open(inner,request,timeout):
                obj=json.loads(request.data)
                self.assertEqual(obj['method'],'getBlock');self.assertEqual(obj['params'][0],100)
                cfg=obj['params'][1]
                self.assertIs(type(cfg['maxSupportedTransactionVersion']),int)
                self.assertEqual(cfg,{'commitment':'finalized','encoding':'json','transactionDetails':'full','maxSupportedTransactionVersion':1,'rewards':False})
                self.assertEqual(timeout,8)
                return io.BytesIO(versioned_block(100,99,1))
        rpc.opener=Transport();wire,err=rpc.block(100)
        self.assertIsNone(err);self.assertEqual(json.loads(wire)['result']['transactions'][0]['version'],1)
    def test_old_zero_reproduces_32015_new_one_succeeds(self):
        rpc=Rpc('https://fixture.invalid')
        class Transport:
            def open(inner,request,timeout):
                cfg=json.loads(request.data)['params'][1]
                return io.BytesIO(error(-32015) if cfg['maxSupportedTransactionVersion']<1 else versioned_block(100,99,1))
        rpc.opener=Transport();rpc.block_config=dict(LEGACY_BLOCK_CONFIG)
        wire,_=rpc.block(100);self.assertEqual(normalize(100,wire,None,context())[:2],('error','rpc_-32015'))
        rpc.block_config=dict(BLOCK_CONFIG);wire,_=rpc.block(100)
        self.assertEqual(normalize(100,wire,None,modern_context())[0],'archived')
    def test_legacy_zero_evidence_survives_upgrade_and_retry(self):
        old=context();sid=self.s.session(old);raw=error(-32015);ident=self.s.capture(100,sid,raw);self.s.apply(ident)
        row=self.s.db.execute('SELECT * FROM attempts WHERE id=?',(ident,)).fetchone()
        old_digest=digest(canonical([100,sid,digest(raw),None,row['observed_at'],'getBlock',LEGACY_BLOCK_CONFIG]).encode())
        self.assertEqual(row['evidence_hash'],old_digest)
        before=tuple(row);client=VersionFixture();self.s.collect(client,retry=True)
        self.assertEqual(client.calls,[100]);self.assertEqual(self.s.audit()['publications'],1)
        self.assertEqual(tuple(self.s.db.execute('SELECT * FROM attempts WHERE id=1').fetchone()),before)
        self.assertEqual(self.s.replay(1)['reason'],'rpc_-32015');self.assertEqual(self.s.replay(2)['status'],'archived')
        self.assertEqual(self.s.audit()['attempt_diagnostics'][0]['request']['params'][1]['maxSupportedTransactionVersion'],0)
        self.assertEqual(self.s.audit()['attempt_diagnostics'][1]['request']['params'][1]['maxSupportedTransactionVersion'],1)
    def test_32015_at_version_one_not_retried_blindly(self):
        sid=self.s.session(modern_context());self.s.apply(self.s.capture(100,sid,error(-32015)))
        client=VersionFixture();self.s.collect(client,retry=True)
        self.assertEqual(client.calls,[]);self.assertEqual(self.s.audit()['counts']['error'],1)
        self.assertEqual(self.s.audit()['publications'],0)
    def test_32603_is_error_retryable_and_history_preserved(self):
        sid=self.s.session(modern_context());self.s.apply(self.s.capture(100,sid,error(-32603)))
        self.assertEqual(self.s.audit()['slots'][0]['status'],'error')
        self.assertEqual(retry_metadata('rpc_-32603')['retry'],'bounded_backoff')
        with patch('astra_blocks.store.time.sleep') as pause:self.s.collect(VersionFixture(),retry=True,retry_round=2)
        pause.assert_called_once_with(0.5)
        self.assertEqual(self.s.replay(1)['reason'],'rpc_-32603');self.assertEqual(self.s.audit()['publications'],1)
    def test_safe_error_diagnostic_exposes_only_numeric_version(self):
        raw=canonical({'jsonrpc':'2.0','id':1,'error':{'code':-32015,
            'message':'Transaction version (1) is not supported; SYNTHETIC_SECRET'}}).encode()
        self.assertEqual(error_diagnostic(raw),{'rpc_code':-32015,'reported_transaction_version':1})
        self.assertNotIn('SYNTHETIC_SECRET',str(error_diagnostic(raw)))
    def test_invalid_rpc_params_not_retried(self):
        sid=self.s.session(modern_context());self.s.apply(self.s.capture(100,sid,error(-32602)))
        client=VersionFixture();self.s.collect(client,retry=True);self.assertEqual(client.calls,[])
    def test_all_transaction_formats_preserved_offline(self):
        sid=self.s.session(modern_context())
        for slot,version in zip((100,101,102),('legacy',0,1)):
            wire=versioned_block(slot,slot-1,version);ident=self.s.capture(slot,sid,wire);self.s.apply(ident)
            doc=json.loads(self.s.replay(ident)['document'])
            self.assertEqual(doc['block']['transactions'][0]['version'],version)
            self.assertEqual(self.s.db.execute('SELECT raw FROM attempts WHERE id=?',(ident,)).fetchone()[0],wire)
        self.assertTrue(self.s.audit()['healthy'])
    def test_audit_version_metadata_corruption_detected(self):
        sid=self.s.session(modern_context());self.s.apply(self.s.capture(100,sid,versioned_block(100,99,1)))
        ctx=modern_context();ctx['block_config']['maxSupportedTransactionVersion']=0
        self.s.db.execute('DROP TRIGGER no_UPDATE_sessions')
        self.s.db.execute('UPDATE sessions SET context=?',(canonical(ctx),));self.s.db.commit()
        self.assertFalse(self.s.audit()['healthy'])
    def test_no_false_pass_all_rpc_errors(self):
        from block_validation import run
        class Broken(VersionFixture):
            def block(self,slot):return error(-32015),None
        folder=Path(self.tmp.name)/'worker';folder.mkdir()
        with patch.object(run,'Rpc',return_value=Broken()):
            for phase in ('first','resume','retry','offline_replay'):
                run.worker(phase,folder);report=json.loads((folder/(phase+'.json')).read_text())
                self.assertEqual(report['status'],'FAIL',phase);self.assertEqual(report['evidence']['publications'],0)
                self.assertEqual(report['evidence']['counts']['skipped'],0)
    def test_retry_internal_error_bounded_to_three_rounds(self):
        from block_validation import run
        class Broken(VersionFixture):
            def block(self,slot):return error(-32603),None
        folder=Path(self.tmp.name)/'worker';folder.mkdir()
        with patch.object(run,'Rpc',return_value=Broken()),patch('astra_blocks.store.time.sleep'):
            for phase in ('first','resume','retry'):run.worker(phase,folder)
        report=json.loads((folder/'retry.json').read_text())
        self.assertEqual(report['status'],'FAIL');self.assertEqual(len(report['evidence']['retry_rounds']),3)
        self.assertEqual(report['evidence']['coverage']['attempts'],24)

class ClockRegressionTests(unittest.TestCase):
    def test_original_clock_invariant_repeated_without_os_clock(self):
        spec=importlib.util.spec_from_file_location('original_foundation',ROOT/'tests/test_foundation.py')
        foundation=importlib.util.module_from_spec(spec);spec.loader.exec_module(foundation)
        with patch('time.time_ns',return_value=0):
            for _ in range(20):
                test=foundation.FoundationTests('test_clock_regression_fail_closed');result=unittest.TestResult();test.run(result)
                self.assertTrue(result.wasSuccessful())
    def test_clock_regression_leaves_no_publication_and_recovery_is_safe(self):
        from astra.store import Store
        from astra.contracts import canonical
        with tempfile.TemporaryDirectory() as d:
            clock=[100_000_000];s=Store(Path(d)/'clock.sqlite',clock=lambda:clock[0])
            try:
                from block_tests.test_blocks import response
                raw=canonical({'schema_version':1,'source':'fixture','source_id':'clock','logical_id':'clock',
                    'kind':'observation','event_time':None,'slot':1,'blockhash':'fixture','commitment':'finalized',
                    'revision':0,'supersedes':None,'retracted':False,'payload':{}}).encode()
                ident=s.capture(raw);s.normalize(ident);clock[0]=1
                with self.assertRaisesRegex(ValueError,'clock regression'):s.publish(ident)
                self.assertEqual(s.db.execute('SELECT COUNT(*) FROM publication').fetchone()[0],0)
                self.assertFalse(s.db.in_transaction)
                clock[0]=100_000_001;s.recover();s.recover()
                self.assertEqual(s.db.execute('SELECT COUNT(*) FROM publication').fetchone()[0],1)
            finally:s.close()
