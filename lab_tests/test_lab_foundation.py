import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_intelligence_lab.contracts import ShadowAnalysisEnvelopeV0, validate_envelope
from astra_intelligence_lab.integrity import canonical, sha256_file, sha256_json
from astra_intelligence_lab.non_influence import attest_non_influence, capture_astra_baseline
from astra_intelligence_lab.reader import (
    read_canonical_dataset,
    read_session_freeze,
    validate_inputs_as_of,
)
from astra_intelligence_lab.session import (
    build_session_manifest,
    replay_lab,
    verify_session_manifest,
)
from astra_intelligence_lab.store import LabStore


def envelope(**changes):
    values = {
        "agent": "BoundaryProbeV0",
        "agent_version": "0.1.0",
        "event_id": "event-1",
        "pool": "pool-1",
        "mint": "mint-1",
        "cutoff_ns": 20,
        "input_hashes": ("a" * 64,),
        "provenance": ({"frame": 1, "observed_ns": 10},),
        "coverage": "OBSERVED_SUBSET",
        "classification": "DERIVED",
        "missing": (),
        "result": {"sample_count": 1, "available_at": 10},
    }
    values.update(changes)
    return ShadowAnalysisEnvelopeV0(**values)


class ContractTests(unittest.TestCase):
    def test_envelope_is_versioned_hashed_and_shadow_only(self):
        value = envelope().document()
        self.assertEqual(value["schema"], "ShadowAnalysisEnvelopeV0")
        self.assertTrue(value["shadow_only"])
        self.assertEqual(len(value["analysis_id"]), 64)
        self.assertEqual(validate_envelope(value), value)

    def test_all_astra_decisions_are_forbidden_at_any_depth(self):
        for action in ("BUY", "SELL", "HOLD", "CANDIDATE_BUY", "EXIT_CANDIDATE"):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "decision_forbidden"):
                envelope(result={"nested": [{"action": action}]}).document()

    def test_future_information_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "future_information"):
            envelope(result={"observed_ns": 21}).document()
        with self.assertRaisesRegex(ValueError, "future_information"):
            validate_inputs_as_of({"available_at": 21}, 20)

    def test_unknown_is_never_numeric_zero(self):
        value = envelope(classification="UNKNOWN", missing=("liquidity",), result=None).document()
        self.assertIsNone(value["result"])
        with self.assertRaisesRegex(ValueError, "unknown_must_be_null"):
            envelope(result={"metric": {"status": "UNKNOWN", "value": 0}}).document()
        with self.assertRaisesRegex(ValueError, "unknown_requires_null"):
            envelope(classification="UNKNOWN", missing=("liquidity",), result=0).document()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_only_chain_idempotence_and_deterministic_replay(self):
        path = self.root / "lab.sqlite"
        store = LabStore(path)
        first = envelope()
        second = envelope(event_id="event-2", input_hashes=("b" * 64,))
        self.assertTrue(store.append(first))
        self.assertFalse(store.append(first))
        self.assertTrue(store.append(second))
        expected = store.replay()
        audit = store.audit()
        store.close()
        before_replay = path.read_bytes()
        with patch.object(socket, "create_connection", side_effect=AssertionError("network used")):
            replayed = replay_lab(path)
        self.assertEqual(path.read_bytes(), before_replay)
        self.assertEqual(replayed["records"], expected)
        self.assertEqual(replayed["records_sha256"], sha256_json(expected))
        self.assertEqual(replayed["store"], audit)
        self.assertFalse(replayed["network_used"])

    def test_mutation_and_corruption_fail_closed(self):
        store = LabStore(self.root / "lab.sqlite")
        store.append(envelope())
        with self.assertRaises(sqlite3.IntegrityError):
            store.db.execute("UPDATE lab_records SET document='{}'")
        store.db.rollback()
        store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
        store.db.execute("UPDATE lab_records SET document='{}'")
        store.db.commit()
        with self.assertRaisesRegex(ValueError, "chain_hash_mismatch"):
            store.replay()
        store.close()

    def test_unrelated_database_is_refused_without_change(self):
        path = self.root / "other.sqlite"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE unrelated(value)")
        db.commit()
        db.close()
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "foreign_database"):
            LabStore(path)
        self.assertEqual(path.read_bytes(), before)


class ReaderAndNonInfluenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "astra-session"
        (self.source / "state").mkdir(parents=True)
        raw = sqlite3.connect(self.source / "raw.sqlite")
        raw.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT)")
        frames = [
            {"kind": "brain_decision", "metadata": {"id": "brain-1"}},
            {"kind": "position_health", "metadata": {"id": "health-1"}},
        ]
        previous = "0" * 64
        for seq, frame in enumerate(frames, 1):
            document = canonical(frame)
            digest = sha256_json([seq, document, previous])
            raw.execute("INSERT INTO frames VALUES(?,?,?,?)", (seq, document, previous, digest))
            previous = digest
        raw.commit()
        raw.close()
        paper = sqlite3.connect(self.source / "state" / "paper.sqlite")
        paper.execute("CREATE TABLE ledger(seq INTEGER PRIMARY KEY,id TEXT,doc TEXT,prev TEXT,hash TEXT)")
        paper.execute("INSERT INTO ledger VALUES(1,'intent-1','{}',?,?)", ("0" * 64, "c" * 64))
        paper.commit()
        paper.close()

    def tearDown(self):
        self.tmp.cleanup()

    def dataset(self):
        value = {
            "schema": "BrainSessionDatasetV0",
            "decisions": [],
            "coverage": "OBSERVED_SUBSET",
            "unobserved_opportunities": "UNKNOWN",
        }
        value["dataset_sha256"] = sha256_json(value)
        return value

    def test_dataset_and_freeze_are_verified_read_only(self):
        dataset_path = self.root / "dataset.json"
        dataset_path.write_text(canonical(self.dataset()), encoding="utf-8")
        before = dataset_path.read_bytes()
        direct = read_canonical_dataset(dataset_path)
        self.assertEqual(dataset_path.read_bytes(), before)
        freeze = self.root / "freeze"
        freeze.mkdir()
        (freeze / "dataset.json").write_bytes(before)
        files = {"dataset.json": sha256_file(freeze / "dataset.json")}
        manifest = {
            "schema": "SessionFreezeV0",
            "files": files,
            "dataset_sha256": direct.dataset_sha256,
            "configuration_hash": "d" * 64,
            "promotion_allowed": False,
        }
        manifest["freeze_id"] = sha256_json(manifest)
        (freeze / "manifest.json").write_text(canonical(manifest), encoding="utf-8")
        file_hashes = {p.name: sha256_file(p) for p in freeze.iterdir()}
        loaded = read_session_freeze(freeze)
        self.assertEqual(loaded.dataset_sha256, direct.dataset_sha256)
        self.assertEqual(loaded.source_identity, manifest["freeze_id"])
        self.assertEqual(file_hashes, {p.name: sha256_file(p) for p in freeze.iterdir()})
        self.assertFalse(loaded.network_used)

    def test_dataset_tampering_and_unknown_zero_are_rejected(self):
        bad = self.dataset()
        bad["coverage"] = "CHANGED"
        path = self.root / "bad.json"
        path.write_text(canonical(bad), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "dataset_hash_mismatch"):
            read_canonical_dataset(path)
        unknown = self.dataset()
        unknown["bad"] = {"status": "UNKNOWN", "value": 0}
        unknown["dataset_sha256"] = sha256_json({k: v for k, v in unknown.items() if k != "dataset_sha256"})
        path.write_text(canonical(unknown), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown_must_be_null"):
            read_canonical_dataset(path)

    def test_lab_run_does_not_modify_astra_archive_ledger_brain_or_health(self):
        before = capture_astra_baseline(self.source)
        astra_files = {
            path.relative_to(self.source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.source.rglob("*")
            if path.is_file()
        }
        lab = self.root / "lab"
        store = LabStore(lab / "lab.sqlite")
        store.append(envelope())
        records = store.replay()
        store.close()
        after = capture_astra_baseline(self.source)
        attestation = attest_non_influence(before, after)
        self.assertTrue(attestation["unchanged"])
        self.assertTrue(all(value is True for key, value in attestation.items() if key.endswith("_unchanged")))
        self.assertEqual(attestation["lab_writes_to_astra"], 0)
        self.assertEqual(
            astra_files,
            {
                path.relative_to(self.source).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.source.rglob("*")
                if path.is_file()
            },
        )
        manifest = build_session_manifest(
            lab / "manifest.json", lab / "lab.sqlite", "fixture-source", attestation
        )
        self.assertFalse(manifest["promotion_allowed"])
        self.assertEqual(verify_session_manifest(lab / "manifest.json")["status"], "PASS")
        self.assertEqual(replay_lab(lab / "lab.sqlite")["records"], records)


if __name__ == "__main__":
    unittest.main()
