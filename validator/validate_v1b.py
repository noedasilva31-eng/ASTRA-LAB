"""Non-destructive ASTRA V1b integration validator. Python 3.12+, stdlib only."""
import argparse
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

CASES = [
 ('foundation', 'Suite de tests existante du depot'),
 ('live_rpc', 'Capture RPC reelle et ingestion'),
 ('raw_bytes', 'Brut RPC conserve octet pour octet avant transformation'),
 ('replay', 'Replay hors reseau depuis le brut archive'),
 ('before_normalize', 'Arret brutal apres capture, avant normalisation'),
 ('before_publish', 'Arret brutal apres normalisation, avant publication'),
 ('recover_twice', 'Recover idempotent, lignes et publications inchangees'),
 ('redelivery', 'Redelivery et deduplication'),
 ('conflict', 'Conflit identite source et quarantaine'),
 ('continue', 'Ingestion apres quarantaine'),
 ('backup', 'Backup et restauration locale, snapshots et replays'),
 ('hashes', 'Hashes bruts/documents et detection de corruption'),
 ('outage', 'RPC muet, timeout borne, aucune ecriture'),
 ('after_outage', 'Nouvelle collecte reelle apres panne simulee'),
]

class CheckError(Exception):
    pass


def check(condition, code):
    if not condition:
        raise CheckError(code)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def blob(value):
    return base64.b64encode(value).decode('ascii')


def unblob(value):
    return base64.b64decode(value)


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding='utf-8')


def child_env(live=False):
    # No endpoint in command lines; unrelated credentials are not inherited.
    allowed = ('PATH', 'SystemRoot', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'SYSTEMDRIVE',
               'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR')
    result = {k: os.environ[k] for k in allowed if k in os.environ}
    result['PYTHONDONTWRITEBYTECODE'] = '1'
    if live and os.environ.get('SOLANA_RPC_URL'):
        result['SOLANA_RPC_URL'] = os.environ['SOLANA_RPC_URL']
    return result


def run_child(args, root, timeout=30, live=False):
    try:
        p = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), *args],
                           cwd=root, env=child_env(live), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout, check=False)
        return p.returncode
    except subprocess.TimeoutExpired:
        return 124


def adapter(root):
    sys.path.insert(0, str(Path(root) / 'project'))
    spec = importlib.util.spec_from_file_location('v1b_adapter', Path(root) / 'adapter.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline():
    def denied(*args, **kwargs):
        raise CheckError('unexpected_network_access')
    socket.create_connection = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def normalized(s, ident):
    return s.db.execute('SELECT status,reason,document,document_hash FROM normalization WHERE capture_id=?', (ident,)).fetchone()


def logical_state(s):
    # Exact rows, including hashes, IDs and publication timestamps.
    return {t: [tuple(r) for r in s.db.execute('SELECT * FROM ' + t + ' ORDER BY 1')]
            for t in ('raw_capture', 'rpc_provenance', 'normalization', 'publication')}


def health(s, accepted, duplicate=0, quarantined=0, pending=0, unpublished=0):
    h = s.health()
    for k, expected in [('accepted', accepted), ('duplicate', duplicate), ('quarantined', quarantined)]:
        check(h['counts'].get(k, 0) == expected, 'count_' + k)
    for k, expected in [('pending', pending), ('unpublished', unpublished),
                        ('integrity', 'ok'), ('raw_hash_errors', 0), ('document_hash_errors', 0)]:
        check(h[k] == expected, 'health_' + k)
    check(h['healthy'] == (quarantined == pending == unpublished == 0), 'healthy_semantics')
    pubs = s.db.execute('SELECT count(*) FROM publication').fetchone()[0]
    check(pubs == accepted - unpublished, 'publication_count')
    return dict(h, publication_count=pubs)


def ingest(a, s, wire):
    ident = a.capture(s, wire)
    status = s.normalize(ident)
    s.publish(ident)
    return ident, status


def assert_replay(a, s, ident):
    row = normalized(s, ident)
    value = a.replay(s, ident)
    check(isinstance(value, bytes), 'adapter_replay_must_return_document_bytes')
    check(value == row['document'].encode('utf-8'), 'replay_document_mismatch')
    check(sha(value) == row['document_hash'], 'replay_hash_mismatch')
    return {'capture_id': ident, 'match': True, 'document_hash': sha(value), 'replayed_hash': sha(value)}


def variant(wire, distinct=False):
    obj = json.loads(wire)
    if distinct:
        obj['result']['context']['slot'] += 1
        obj['result']['value']['blockhash'] = 'SYNTHETIC-VALIDATION-DISTINCT'
    else:
        obj['result']['value']['lastValidBlockHeight'] += 1
    return json.dumps(obj, separators=(',', ':')).encode()


def check_secret_echo(wire, endpoint):
    parts = urllib.parse.urlsplit(endpoint)
    needles = [endpoint, parts.username, parts.password]
    needles += [v for _, v in urllib.parse.parse_qsl(parts.query)]
    needles += [s for s in parts.path.split('/') if len(s) >= 12]
    text = wire.decode('utf-8')
    check(not any(n and len(n) >= 4 and (n in text or urllib.parse.quote(n, safe='') in text)
                  for n in needles), 'response_echoes_endpoint_credentials')


def fetch_worker(root, dest):
    a = adapter(root)
    endpoint = os.environ.get('SOLANA_RPC_URL', '')
    check(bool(endpoint), 'SOLANA_RPC_URL_missing')
    check(urllib.parse.urlsplit(endpoint).scheme == 'https', 'endpoint_must_use_https')
    wire, document, provenance = a.fetch(endpoint)
    check_secret_echo(wire, endpoint)
    obj = json.loads(wire)
    check(obj.get('jsonrpc') == '2.0' and 'error' not in obj, 'rpc_response_invalid')
    check(isinstance(obj['result']['context']['slot'], int), 'rpc_slot_invalid')
    save(dest, {'wire': blob(wire), 'document': blob(document), 'origin': 'real_rpc', 'provenance': provenance})


def crash_worker(root, path, fixture, stage):
    offline()
    a = adapter(root)
    s = a.Store(path)
    data = json.loads(Path(fixture).read_text())
    a.configure(data['provenance'])
    wire = unblob(data['wire'])
    ident = a.capture(s, wire)
    if stage == 'before_publish':
        check(s.normalize(ident) == 'accepted', 'crash_seed_not_accepted')
    # Deliberate process exit without Store.close(): committed transaction boundary.
    os._exit(73)


def execute_case(root, case):
    a = adapter(root)
    data = json.loads((Path(root) / 'fixture.json').read_text())
    wire = unblob(data['wire'])
    a.configure(data['provenance'])
    base = Path(root) / case
    base.mkdir()
    path = base / 'test.sqlite'
    evidence = {'origin': data['origin'], 'scope': 'production APIs via explicit adapter'}
    if case != 'outage' and case != 'after_outage':
        offline()
    if case in ('before_normalize', 'before_publish'):
        rc = run_child(['--crash', str(root), str(path), str(Path(root) / 'fixture.json'), case], root)
        check(rc == 73, 'crash_checkpoint_not_reached')
    s = a.Store(path)
    try:
        if case == 'foundation':
            import unittest
            project = Path(root) / 'project'
            check((project / 'tests').is_dir(), 'project_tests_missing')
            os.chdir(project)
            suite = unittest.defaultTestLoader.discover(str(project / 'tests'))
            class Results(unittest.TestResult):
                def __init__(self):
                    super().__init__()
                    self.records = []
                def addSuccess(self, test):
                    super().addSuccess(test)
                    self.records.append({'test': test.id(), 'status': 'PASS'})
                def addFailure(self, test, err):
                    super().addFailure(test, err)
                    self.records.append({'test': test.id(), 'status': 'FAIL'})
                def addError(self, test, err):
                    super().addError(test, err)
                    self.records.append({'test': test.id(), 'status': 'FAIL'})
                def addSkip(self, test, reason):
                    super().addSkip(test, reason)
                    self.records.append({'test': test.id(), 'status': 'FAIL', 'code': 'skipped'})
            result = Results()
            suite.run(result)
            evidence['tests'] = result.records
            evidence['count'] = result.testsRun
            evidence['suite_pass'] = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        elif case == 'live_rpc':
            check(data['origin'] == 'real_rpc', 'live_capture_unavailable')
            ident, status = ingest(a, s, wire)
            check(status == 'accepted', 'live_not_accepted')
            check(normalized(s, ident)['document'].encode() == unblob(data['document']), 'live_document_mismatch')
            evidence['health'] = health(s, 1)
        elif case == 'raw_bytes':
            ident = a.capture(s, wire)
            row = a.raw_row(s, ident)
            check(bytes(row[0]) == wire, 'original_rpc_bytes_not_archived')
            check(row[1] == sha(wire) and row[2] > 0, 'raw_hash_or_receipt_invalid')
            health(s, 0, pending=1)
            check(s._rpc_provenance(ident) == data['provenance'], 'provenance_mismatch')
            evidence['provenance_preserved'] = True
            evidence['raw_sha256'] = sha(wire)
        elif case == 'replay':
            ident, status = ingest(a, s, wire)
            check(status == 'accepted', 'not_accepted')
            before = logical_state(s)
            evidence['replay'] = assert_replay(a, s, ident)
            check(logical_state(s) == before, 'replay_mutates_store')
        elif case in ('before_normalize', 'before_publish'):
            if case == 'before_normalize':
                health(s, 0, pending=1)
            else:
                health(s, 1, unpublished=1)
            s.recover()
            evidence['health'] = health(s, 1)
            check(s.db.execute('SELECT count(*) FROM raw_capture').fetchone()[0] == 1, 'recovery_adds_capture')
            evidence['replay'] = assert_replay(a, s, 1)
            check(normalized(s, 1)['document'].encode() == a.normalize_wire(wire), 'recovery_document_mismatch')
        elif case == 'recover_twice':
            ingest(a, s, wire)
            before = logical_state(s)
            s.recover(); s.recover()
            check(logical_state(s) == before, 'recover_mutates_committed_rows')
            evidence['health'] = health(s, 1)
        elif case == 'redelivery':
            ident, _ = ingest(a, s, wire)
            original = tuple(normalized(s, ident))
            publication = list(s.db.execute('SELECT * FROM publication'))
            delivered = s.redeliver_rpc(ident)
            status = delivered['status']
            check(bytes(a.raw_row(s, delivered['capture_id'])[0]) == wire, 'redelivery_raw_changed')
            check(status == 'duplicate', 'redelivery_not_duplicate')
            s.recover()
            check(tuple(normalized(s, ident)) == original, 'original_changed')
            check(list(s.db.execute('SELECT * FROM publication')) == publication, 'duplicate_published')
            evidence['health'] = health(s, 1, duplicate=1)
        elif case in ('conflict', 'continue', 'backup'):
            ident, _ = ingest(a, s, wire)
            original = tuple(normalized(s, ident))
            conflict_result = s.conflict_rpc(ident)
            bad, status = conflict_result['capture_id'], conflict_result['status']
            check(status == 'quarantined', 'conflict_not_quarantined')
            check(normalized(s, bad)['reason'] == 'source ID conflict', 'conflict_reason')
            check(tuple(normalized(s, ident)) == original, 'conflict_changed_original')
            check(bytes(a.raw_row(s, ident)[0]) == wire, 'conflict_changed_raw')
            evidence['original_replay'] = assert_replay(a, s, ident)
            evidence['mutations'] = 'synthetic conflict; synthetic distinct identity for offline isolation'
            n = 1
            if case in ('continue', 'backup'):
                third, status = ingest(a, s, variant(wire, distinct=True))
                check(status == 'accepted', 'quarantine_blocks_valid_ingestion')
                n = 2
            s.recover()
            evidence['health'] = health(s, n, quarantined=1)
            if case == 'backup':
                backup = base / 'backup.sqlite'
                restore = base / 'restored.sqlite'
                s.backup(backup)
                shutil.copyfile(backup, restore)
                other = a.Store(restore)
                try:
                    before = logical_state(s)
                    check(logical_state(other) == before, 'restore_rows_differ')
                    cutoff = 2**62
                    check(s.snapshot(cutoff) == other.snapshot(cutoff), 'restore_snapshot_differs')
                    other.recover(); other.recover()
                    check(logical_state(other) == before, 'restored_recover_mutates_rows')
                    evidence['restored_health'] = health(other, 2, quarantined=1)
                    evidence['replays'] = [assert_replay(a, other, i) for i in (ident, third)]
                finally:
                    other.close()
        elif case == 'hashes':
            ident, _ = ingest(a, s, wire)
            for row in s.db.execute('SELECT raw,hash FROM raw_capture'):
                check(sha(bytes(row[0])) == row[1], 'raw_digest_mismatch')
            for row in s.db.execute('SELECT document,document_hash FROM normalization WHERE document IS NOT NULL'):
                check(sha(row[0].encode()) == row[1], 'document_digest_mismatch')
            evidence['health_before'] = health(s, 1)
            # Corruption injection confined to this disposable test DB.
            s.db.execute('DROP TRIGGER no_UPDATE_raw_capture')
            s.db.execute('UPDATE raw_capture SET raw=? WHERE id=?', (b'corrupt', ident)); s.db.commit()
            check(s.health()['raw_hash_errors'] == 1 and not s.health()['healthy'], 'raw_corruption_not_detected')
            s.db.execute('DROP TRIGGER no_UPDATE_normalization')
            s.db.execute("UPDATE normalization SET document='{}' WHERE capture_id=?", (ident,)); s.db.commit()
            check(s.health()['document_hash_errors'] == 1, 'document_corruption_not_detected')
            evidence['corruptions_detected'] = ['raw', 'document']
        elif case == 'outage':
            ingest(a, s, wire)
            before = logical_state(s)
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(2)
            stop = threading.Event()
            connected = threading.Event()
            def blackhole():
                try:
                    conn, _ = listener.accept()
                    with conn:
                        connected.set()
                        stop.wait(22)
                except OSError:
                    pass
            thread = threading.Thread(target=blackhole, daemon=True); thread.start()
            start = time.monotonic()
            failed = False
            try:
                # Genuine TCP connection to a silent local server, no Internet outage needed.
                received, _, _ = a.fetch('http://127.0.0.1:' + str(listener.getsockname()[1]))
                ingest(a, s, received)
            except (TimeoutError, OSError):
                failed = True
            finally:
                elapsed = time.monotonic() - start
                stop.set(); listener.close(); thread.join(2)
            check(connected.is_set(), 'local_outage_server_not_contacted')
            check(failed, 'outage_reported_as_success')
            check(elapsed <= 20, 'rpc_timeout_exceeds_20_seconds')
            check(logical_state(s) == before, 'outage_created_or_changed_rows')
            evidence.update(seconds=round(elapsed, 3), hard_worker_deadline_seconds=25, health=health(s, 1))
        elif case == 'after_outage':
            check(data['origin'] == 'real_rpc', 'live_capture_unavailable')
            ingest(a, s, wire)
            dest = base / 'new.json'
            rc = run_child(['--fetch', str(root), str(dest)], root, timeout=25, live=True)
            check(rc == 0 and dest.exists(), 'live_rpc_reconnection_failed')
            next_data = json.loads(dest.read_text())
            a.configure(next_data['provenance'])
            next_wire = unblob(next_data['wire'])
            check(a.normalize_wire(next_wire) != a.normalize_wire(wire), 'new_real_identity_not_observed')
            ident, status = ingest(a, s, next_wire)
            check(status == 'accepted', 'reconnection_not_accepted')
            evidence['health'] = health(s, 2)
            evidence['new_replay'] = assert_replay(a, s, ident)
        return evidence
    finally:
        s.close()


def worker(root, case, dest):
    started = time.monotonic()
    result = {'id': case, 'status': 'FAIL'}
    # Never persist arbitrary exceptions, tracebacks, endpoint URLs or payloads.
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result['evidence'] = execute_case(Path(root), case)
        result['status'] = 'PASS' if result['evidence'].get('suite_pass', True) else 'FAIL'
    except CheckError as exc:
        result['code'] = str(exc)  # only runner-owned static codes
    except Exception as exc:
        result['code'] = ('original_rpc_bytes_not_archived' if str(exc) == 'original_rpc_bytes_not_archived'
                          else 'adapter_or_product_error')
        result['error_type'] = type(exc).__name__ if type(exc).__module__ == 'builtins' else 'AdapterError'
    result['seconds'] = round(time.monotonic() - started, 3)
    save(dest, result)


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ('--fetch', '--crash', '--case'):
        try:
            if sys.argv[1] == '--fetch': fetch_worker(*sys.argv[2:])
            elif sys.argv[1] == '--crash': crash_worker(*sys.argv[2:])
            else: worker(*sys.argv[2:])
            return 0
        except Exception:
            return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path, help='Project root containing astra/store.py')
    parser.add_argument('--adapter', type=Path, default=Path(__file__).with_name('adapter_current.py'))
    parser.add_argument('--self-test', action='store_true', help='Synthetic transport fixture; never validates real RPC')
    args = parser.parse_args()
    source = args.project.resolve() / 'astra'
    if not (source / 'store.py').is_file() or not args.adapter.is_file():
        print('FAIL: project or adapter missing. See README.'); return 2
    # Reports get a NEW directory beside runner. No overwrite and no DB path argument.
    reports = Path(tempfile.mkdtemp(prefix='v1b-report-', dir=Path(__file__).resolve().parent))
    with tempfile.TemporaryDirectory(prefix='astra-v1b-isolated-') as tmp:
        root = Path(tmp)
        copied = root / 'project' / 'astra'; copied.mkdir(parents=True)
        fingerprint = hashlib.sha256()
        count = 0
        for file in sorted(source.rglob('*.py')):
            if file.is_symlink() or any(p.is_symlink() for p in file.parents if p != source.parent):
                continue
            relative = file.relative_to(source)
            dest = copied / relative; dest.parent.mkdir(parents=True, exist_ok=True)
            content = file.read_bytes(); dest.write_bytes(content)
            fingerprint.update(str(relative).replace('\\', '/').encode() + b'\0' + content)
            count += 1
        source_tests = args.project.resolve() / 'tests'
        if source_tests.is_dir() and not source_tests.is_symlink():
            for file in sorted(source_tests.rglob('*.py')):
                if file.is_symlink() or any(p.is_symlink() for p in file.parents):
                    continue
                relative = file.relative_to(source_tests)
                dest = root / 'project' / 'tests' / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                content = file.read_bytes(); dest.write_bytes(content)
                fingerprint.update(b'tests/' + str(relative).replace('\\', '/').encode() + b'\0' + content)
                count += 1
        shutil.copyfile(args.adapter, root / 'adapter.py')
        fixture = root / 'fixture.json'
        live_ok = False
        if not args.self_test and os.environ.get('SOLANA_RPC_URL'):
            print('Capture RPC reelle (endpoint masque, delai global maximal 25 s)...', flush=True)
            live_ok = run_child(['--fetch', str(root), str(fixture)], root, 25, live=True) == 0 and fixture.exists()
        if not live_ok:
            raw = json.dumps({'jsonrpc': '2.0', 'id': 1, 'result': {'context': {'slot': 100},
                'value': {'blockhash': 'SYNTHETIC-VALIDATION', 'lastValidBlockHeight': 200}}}).encode()
            save(fixture, {'wire': blob(raw), 'origin': 'synthetic_fallback', 'document': '',
                'provenance': {'network':'solana-devnet','provider':'validation-fixture',
                 'endpoint':'https://fixture.invalid','rpc_method':'getLatestBlockhash',
                 'request_params':[{'commitment':'finalized'}]}})
        results = []
        for case, label in CASES:
            dest = root / (case + '.json')
            # after_outage is run only after the controlled outage was demonstrated.
            if case == 'after_outage' and results[-1]['status'] != 'PASS':
                result = {'id': case, 'status': 'FAIL', 'code': 'outage_prerequisite_failed'}
            else:
                rc = run_child(['--case', str(root), case, str(dest)], root,
                               timeout=30 if case == 'after_outage' else 25,
                               live=case == 'after_outage')
                result = json.loads(dest.read_text()) if rc == 0 and dest.exists() else {
                    'id': case, 'status': 'FAIL', 'code': 'worker_timeout' if rc == 124 else 'worker_failed'}
            result['criterion'] = label
            results.append(result)
            print(result['status'] + ' | ' + label + (' | ' + result['code'] if 'code' in result else ''), flush=True)
        report = {'schema_version': 1, 'overall': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'FAIL',
                  'scope': 'V1b implemented primitives only; not full V1 gate',
                  'source_sha256': fingerprint.hexdigest(), 'source_python_files': count,
                  'adapter_sha256': sha((root / 'adapter.py').read_bytes()),
                  'real_rpc_captured': live_ok, 'reference_databases_accessed': False,
                  'temporary_databases_deleted_on_normal_exit': True, 'criteria': results}
        save(reports / 'report.json', report)
        lines = ['ASTRA V1b: ' + report['overall'], 'Source SHA256: ' + report['source_sha256'],
                 'RPC reel: ' + str(live_ok), 'Aucune base de reference ouverte.', '']
        for r in results:
            lines += [r['status'] + ' | ' + r['criterion'], json.dumps(r, ensure_ascii=True), '']
        (reports / 'report.txt').write_text('\n'.join(lines), encoding='utf-8')
    print('Rapports : ' + str(reports))
    return 0 if report['overall'] == 'PASS' else 1

if __name__ == '__main__':
    sys.exit(main())
