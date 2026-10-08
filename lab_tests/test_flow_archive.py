import copy
import hashlib
import json
import shutil
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_intelligence_lab.flow_archive import (
    FlowArchiveImporterV0,
    REFERENCE_SOURCE_SHA256,
    create_flow_freeze,
    verify_flow_freeze,
)
from astra_intelligence_lab.flow import FlowObservationV0, observations_available_at, validate_flow_observation
from astra_intelligence_lab.outcome import MAX_TIMESTAMP_NS
from astra_intelligence_lab.integrity import canonical, sha256_file, sha256_json
from astra_intelligence_lab.store import LabStore
from astra_intelligence_lab.store_v1 import IncrementalLabStoreV1
from lab_tests.test_outcome import sources

SOURCE = Path("position_handoff/offline-resume/state/engine.sqlite")
WATCH_COPY = Path("watch_handoff/offline-migration/state/engine.sqlite")


def import_store(path, source=SOURCE):
    importer = FlowArchiveImporterV0(source)
    observations, coverage = importer.read_observations()
    store = IncrementalLabStoreV1(path)
    receipt = importer.import_into(store)
    audit = store.audit()
    store.close()
    return observations, coverage, receipt, audit


class FlowArchiveImporterTests(unittest.TestCase):
    def test_reference_source_imports_51_canonical_swaps_without_observed_time(self):
        observations, coverage = FlowArchiveImporterV0(SOURCE).read_observations()
        self.assertEqual(len(observations), 51)
        self.assertEqual(len({item["observation_id"] for item in observations}), 51)
        self.assertTrue(all(item["schema"] == "FlowObservationV0" for item in observations))
        self.assertTrue(all(item["observed_ns"] is None for item in observations))
        self.assertTrue(all("observed_ns" in item["missing_dimensions"] for item in observations))
        self.assertEqual(coverage["source_events"], 51)
        self.assertEqual(coverage["observations_produced"], 51)
        self.assertEqual(coverage["distinct_pools"], 19)
        self.assertEqual(coverage["distinct_mints"], 12)
        self.assertEqual(coverage["distinct_wallets"], 50)
        self.assertEqual(coverage["missing_dimensions"], {"observed_ns": 51})
        self.assertEqual(coverage["families"]["rejected_pumpswap_layouts"], "BLOCKED")
        corrupted = copy.deepcopy(observations[0]); corrupted["observation_id"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "flow_observation_hash_mismatch"):
            validate_flow_observation(corrupted)

    def test_int64_boundary_and_availability_order_override_slot_order(self):
        first = FlowObservationV0(
            observation_type="SWAP", pool="p", mint="m", wallets={"user": "w1"},
            signature="s1", slot=200, event_id="e1", instruction_index=1,
            inner_instruction_index=0, event_time=1, observed_ns=None, availability_ns=10,
            source_hashes=("a" * 64,), provenance={"source": "test"}, values={},
            coverage="TEST", missing_dimensions=("observed_ns",),
        )
        second = FlowObservationV0(
            observation_type="SWAP", pool="p", mint="m", wallets={"user": "w2"},
            signature="s2", slot=100, event_id="e2", instruction_index=1,
            inner_instruction_index=0, event_time=1, observed_ns=None,
            availability_ns=MAX_TIMESTAMP_NS, source_hashes=("b" * 64,),
            provenance={"source": "test"}, values={}, coverage="TEST",
            missing_dimensions=("observed_ns",),
        )
        self.assertEqual([item["event_id"] for item in observations_available_at([second, first], MAX_TIMESTAMP_NS)], ["e1", "e2"])
        invalid = second.document(); invalid.pop("observation_id"); invalid["availability_ns"] = MAX_TIMESTAMP_NS + 1
        with self.assertRaisesRegex(ValueError, "invalid_flow_availability_time"):
            validate_flow_observation(invalid)

    def test_source_and_watch_copy_are_identical_and_never_double_counted(self):
        self.assertEqual(sha256_file(SOURCE), REFERENCE_SOURCE_SHA256)
        self.assertEqual(sha256_file(WATCH_COPY), REFERENCE_SOURCE_SHA256)
        first, _ = FlowArchiveImporterV0(SOURCE).read_observations()
        duplicate, _ = FlowArchiveImporterV0(WATCH_COPY).read_observations()
        self.assertEqual(first, duplicate)
        with tempfile.TemporaryDirectory() as tmp:
            store = IncrementalLabStoreV1(Path(tmp) / "flow.sqlite")
            one = FlowArchiveImporterV0(SOURCE).import_into(store)
            two = FlowArchiveImporterV0(WATCH_COPY).import_into(store)
            self.assertEqual((one["appended"], one["redelivered"]), (51, 0))
            self.assertEqual((two["appended"], two["redelivered"]), (0, 51))
            self.assertEqual(store.audit()["records"], 51)
            store.close()

    def test_two_independent_imports_have_same_order_ids_and_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a.sqlite"; b = Path(tmp) / "b.sqlite"
            obs_a, coverage_a, _, audit_a = import_store(a)
            obs_b, coverage_b, _, audit_b = import_store(b)
            self.assertEqual(obs_a, obs_b)
            self.assertEqual(coverage_a, coverage_b)
            self.assertEqual(audit_a["head"], audit_b["head"])
            self.assertEqual(sha256_file(a), sha256_file(b))

    def test_source_hash_and_mutation_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "flow_source_hash_mismatch"):
            FlowArchiveImporterV0(SOURCE, "0" * 64).read_observations()
        with patch("astra_intelligence_lab.flow_archive.sha256_file",
                   side_effect=[REFERENCE_SOURCE_SHA256, "f" * 64]):
            with self.assertRaisesRegex(ValueError, "flow_source_changed_during_import"):
                FlowArchiveImporterV0(SOURCE).read_observations()

    def test_rehashed_row_falsification_cannot_preserve_semantic_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source.sqlite"
            shutil.copyfile(SOURCE, path)
            database = sqlite3.connect(path)
            for name, in database.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall():
                database.execute(f'DROP TRIGGER "{name}"')
            seq, encoded = database.execute(
                "SELECT seq,document FROM events ORDER BY seq LIMIT 1"
            ).fetchone()
            document = json.loads(encoded)
            document["wallet"] = "forged-wallet"
            encoded = canonical(document)
            database.execute(
                "UPDATE events SET document=?,hash=? WHERE seq=?",
                (encoded, hashlib.sha256(encoded.encode()).hexdigest(), seq),
            )
            database.commit()
            database.close()
            with self.assertRaisesRegex(
                ValueError, "canonical_event_semantic_hash_mismatch"
            ):
                FlowArchiveImporterV0(path, sha256_file(path)).read_observations()

    def test_event_identity_signature_availability_and_duplicate_tampering_fail(self):
        for field, value in (
            ("id", "f" * 64),
            ("signature", "forged-signature"),
            ("availability_ns", 1),
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "source.sqlite"; shutil.copyfile(SOURCE, path)
                database = sqlite3.connect(path)
                for name, in database.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                    database.execute(f'DROP TRIGGER "{name}"')
                row = database.execute("SELECT seq,id,document FROM events ORDER BY seq LIMIT 1").fetchone()
                document = json.loads(row[2]); document[field] = value
                encoded = canonical(document); digest = hashlib.sha256(encoded.encode()).hexdigest()
                database.execute("UPDATE events SET document=?,hash=? WHERE seq=?", (encoded, digest, row[0]))
                database.commit(); database.close()
                with self.assertRaisesRegex(ValueError, "flow_source_hash_mismatch"):
                    FlowArchiveImporterV0(path).read_observations()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "duplicate.sqlite"
            source = sqlite3.connect(SOURCE.resolve().as_uri() + "?mode=ro", uri=True)
            rows = source.execute("SELECT seq,id,document,hash,semantic FROM events").fetchall(); source.close()
            database = sqlite3.connect(path)
            database.execute("CREATE TABLE events(seq INTEGER,id TEXT,document TEXT,hash TEXT,semantic TEXT)")
            database.executemany("INSERT INTO events VALUES(?,?,?,?,?)", rows + [(999, *rows[0][1:])])
            database.commit(); database.close()
            with self.assertRaisesRegex(ValueError, "duplicate_flow_event"):
                FlowArchiveImporterV0(path, sha256_file(path)).read_observations()

    def test_interrupted_import_resumes_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flow.sqlite"; store = IncrementalLabStoreV1(path)
            store.db.execute(
                "CREATE TRIGGER abort_tenth BEFORE INSERT ON lab_records WHEN NEW.seq=10 "
                "BEGIN SELECT RAISE(ABORT,'simulated interruption'); END"
            ); store.db.commit()
            with self.assertRaises(sqlite3.IntegrityError):
                FlowArchiveImporterV0(SOURCE).import_into(store)
            self.assertEqual(store.audit()["records"], 9)
            store.db.execute("DROP TRIGGER abort_tenth"); store.db.commit()
            receipt = FlowArchiveImporterV0(SOURCE).import_into(store)
            self.assertEqual((receipt["appended"], receipt["redelivered"]), (42, 9))
            self.assertEqual(store.audit()["records"], 51)
            store.close()


class FlowFreezeTests(unittest.TestCase):
    def make_freeze(self, root):
        store_path = root / "store.sqlite"
        observations, coverage, _, _ = import_store(store_path)
        manifest = create_flow_freeze(root / "freeze", store_path, coverage, [SOURCE, WATCH_COPY])
        return observations, coverage, manifest, root / "freeze"

    def test_freeze_is_deterministic_content_addressed_and_deduplicates_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); first = root / "first"; second = root / "second"; first.mkdir(); second.mkdir()
            _, coverage_a, manifest_a, freeze_a = self.make_freeze(first)
            _, coverage_b, manifest_b, freeze_b = self.make_freeze(second)
            self.assertEqual(coverage_a, coverage_b)
            self.assertEqual(manifest_a, manifest_b)
            self.assertEqual(len(manifest_a["source_identities"]), 1)
            self.assertEqual(manifest_a["record_count"], 51)
            self.assertEqual(
                {p.name: sha256_file(p) for p in freeze_a.iterdir()},
                {p.name: sha256_file(p) for p in freeze_b.iterdir()},
            )

    def test_cutoff_replay_boundaries_and_equal_availability(self):
        with tempfile.TemporaryDirectory() as tmp:
            observations, _, _, freeze = self.make_freeze(Path(tmp))
            times = sorted({item["availability_ns"] for item in observations})
            before = verify_flow_freeze(freeze, times[0] - 1)
            first = verify_flow_freeze(freeze, times[0])
            between = verify_flow_freeze(freeze, times[1] - 1)
            exact = verify_flow_freeze(freeze, times[1])
            after = verify_flow_freeze(freeze, times[-1] + 1)
            self.assertEqual([len(x["observations"]) for x in (before, first, between, exact, after)], [0, 1, 1, 2, 51])
            duplicate_time = next(t for t in times if sum(item["availability_ns"] == t for item in observations) == 2)
            at_duplicate = verify_flow_freeze(freeze, duplicate_time)
            self.assertEqual(sum(item["availability_ns"] == duplicate_time for item in at_duplicate["observations"]), 2)
            self.assertTrue(all(item["availability_ns"] <= duplicate_time for item in at_duplicate["observations"]))

    def test_replay_is_readonly_and_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, freeze = self.make_freeze(Path(tmp)); before = {p.name: sha256_file(p) for p in freeze.iterdir()}
            with patch.object(socket, "create_connection", side_effect=AssertionError("network used")):
                receipt = verify_flow_freeze(freeze)
            self.assertEqual(len(receipt["observations"]), 51)
            self.assertFalse(receipt["network_used"])
            self.assertEqual(receipt["lab_writes_to_astra"], 0)
            self.assertEqual({p.name: sha256_file(p) for p in freeze.iterdir()}, before)

    def test_manifest_coverage_missing_extra_and_file_tampering_fail(self):
        mutations = ("manifest", "coverage", "missing", "extra", "store")
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); _, _, _, freeze = self.make_freeze(root)
                if mutation == "manifest":
                    document = json.loads((freeze / "manifest.json").read_text()); document["record_count"] = 50
                    (freeze / "manifest.json").write_text(canonical(document))
                elif mutation == "coverage":
                    (freeze / "coverage.json").write_text("{}")
                elif mutation == "missing":
                    (freeze / "coverage.json").unlink()
                elif mutation == "extra":
                    (freeze / "undeclared.bin").write_bytes(b"x")
                else:
                    with (freeze / "flow-store-v1.sqlite").open("r+b") as handle:
                        handle.seek(100); handle.write(b"tamper")
                with self.assertRaises(ValueError):
                    verify_flow_freeze(freeze)

    def test_v0_store_cannot_be_frozen_as_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); path = root / "v0.sqlite"; old = LabStore(path); old.append(sources()[0]); old.close()
            _, coverage = FlowArchiveImporterV0(SOURCE).read_observations()
            with self.assertRaisesRegex(ValueError, "lab_v1_migration_forbidden"):
                create_flow_freeze(root / "freeze", path, coverage, [SOURCE])


if __name__ == "__main__":
    unittest.main()
