import ast
import copy
import hashlib
import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_intelligence_lab.fusion import (
    AgentFusionRecordV0,
    create_fusion_record,
    validate_fusion_record,
)
from astra_intelligence_lab.integrity import canonical, sha256_json
from astra_intelligence_lab.launch import analyze_launch
from astra_intelligence_lab.liquidity import analyze_liquidity
from astra_intelligence_lab.non_influence import attest_non_influence, capture_astra_baseline
from astra_intelligence_lab.session import replay_lab
from astra_intelligence_lab.store import LabStore


def launch(event="event", cutoff=20, at=10):
    return analyze_launch(
        event_id=event,
        pool="pool",
        mint="mint",
        cutoff_ns=cutoff,
        observations=[{"observed_ns": at, "kind": "swap", "provenance": {"frame": 1}}],
    )


def liquidity(event="event", cutoff=20, at=10, reserve=1_000):
    return analyze_liquidity(
        event_id=event,
        pool="pool",
        mint="mint",
        cutoff_ns=cutoff,
        observations=[{
            "quote_reserve_raw": reserve,
            "base_reserve_raw": 500,
            "observed_ns": at,
            "provenance": {"frame": 2},
        }],
    )


class FusionContractTests(unittest.TestCase):
    def test_liquidity_and_launch_fusion_contract(self):
        record = create_fusion_record([liquidity(), launch()]).document()
        self.assertEqual(record["schema"], "AgentFusionRecordV0")
        self.assertEqual(record["fusion_version"], "AgentFusionRecorderV0")
        self.assertEqual(record["temporal_rule"], "EXACT_IDENTITY_AND_CUTOFF_V0")
        self.assertEqual(record["present_agents"], ["LaunchAgentV0", "LiquidityAgentV0"])
        self.assertEqual(record["missing_agents"], [])
        self.assertTrue(record["shadow_only"])
        self.assertEqual(record["decision_effect"], "NONE")
        self.assertEqual(validate_fusion_record(record), record)

    def test_agent_order_does_not_change_fusion_id(self):
        first = create_fusion_record([liquidity(), launch()]).document()
        second = create_fusion_record([launch(), liquidity()]).document()
        self.assertEqual(first, second)
        self.assertEqual(first["fusion_id"], second["fusion_id"])

    def test_same_inputs_same_id_and_changed_analysis_changes_id(self):
        baseline = create_fusion_record([launch(), liquidity()]).document()
        repeated = create_fusion_record([launch(), liquidity()]).document()
        changed = create_fusion_record([launch(), liquidity(reserve=1_250)]).document()
        self.assertEqual(baseline["fusion_id"], repeated["fusion_id"])
        self.assertNotEqual(
            baseline["agents"]["LiquidityAgentV0"]["analysis_id"],
            changed["agents"]["LiquidityAgentV0"]["analysis_id"],
        )
        self.assertNotEqual(baseline["fusion_id"], changed["fusion_id"])

    def test_missing_liquidity_is_explicit_unknown_not_zero(self):
        record = create_fusion_record([launch()]).document()
        missing = record["agents"]["LiquidityAgentV0"]
        self.assertEqual(record["missing_agents"], ["LiquidityAgentV0"])
        self.assertEqual(missing["status"], "MISSING")
        self.assertEqual(missing["classification"], "UNKNOWN")
        self.assertIsNone(missing["analysis_id"])
        self.assertNotEqual(missing["analysis_id"], 0)
        self.assertEqual(missing["missing"], ["agent_analysis"])

    def test_missing_launch_is_explicit_unknown_not_zero(self):
        record = create_fusion_record([liquidity()]).document()
        missing = record["agents"]["LaunchAgentV0"]
        self.assertEqual(record["missing_agents"], ["LaunchAgentV0"])
        self.assertEqual(missing["coverage"], "UNKNOWN")
        self.assertIsNone(missing["cutoff_ns"])
        self.assertNotEqual(missing["cutoff_ns"], 0)

    def test_present_agent_unknown_classification_is_preserved(self):
        unknown_launch = analyze_launch(
            event_id="event", pool="pool", mint="mint", cutoff_ns=20, observations=[]
        )
        record = create_fusion_record([unknown_launch, liquidity()]).document()
        reference = record["agents"]["LaunchAgentV0"]
        self.assertEqual(reference["status"], "PRESENT")
        self.assertEqual(reference["classification"], "UNKNOWN")
        self.assertTrue(reference["missing"])

    def test_temporal_or_context_incompatibility_is_refused(self):
        with self.assertRaisesRegex(ValueError, "fusion_cutoff_mismatch"):
            create_fusion_record([launch(cutoff=20), liquidity(cutoff=21)])
        with self.assertRaisesRegex(ValueError, "fusion_cutoff_mismatch"):
            create_fusion_record([launch()], cutoff_ns=19)
        with self.assertRaisesRegex(ValueError, "fusion_context_mismatch"):
            create_fusion_record([launch(), liquidity(event="other")])

    def test_future_information_in_record_is_refused(self):
        record = create_fusion_record([launch(), liquidity()]).document()
        record["agents"]["LaunchAgentV0"]["provenance"].append({"observed_ns": 21})
        record.pop("fusion_id")
        record["fusion_id"] = sha256_json(record)
        with self.assertRaisesRegex(ValueError, "shadow_future_information"):
            validate_fusion_record(record)

    def test_corrupt_source_analysis_id_is_refused(self):
        source_launch = launch().document()
        with self.assertRaisesRegex(ValueError, "shadow_analysis_hash_mismatch"):
            create_fusion_record([dict(source_launch, analysis_id="0" * 64), liquidity()])

    def test_no_decision_or_score_fields_are_produced(self):
        record = create_fusion_record([launch(), liquidity()]).document()
        encoded = json.dumps(record).upper()
        for forbidden in ("BUY", "SELL", "HOLD", "ENTER", "EXIT", "CANDIDATE_BUY", "EXIT_CANDIDATE"):
            self.assertNotIn(f'"{forbidden}"', encoded)
        self.assertNotIn("score", encoded.lower())
        self.assertNotIn("weight", encoded.lower())


class FusionStoreTests(unittest.TestCase):
    def test_append_idempotence_reference_integrity_and_offline_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lab.sqlite"
            launch_envelope = launch()
            liquidity_envelope = liquidity()
            fusion = create_fusion_record([launch_envelope, liquidity_envelope])
            store = LabStore(path)
            store.append(launch_envelope)
            store.append(liquidity_envelope)
            self.assertTrue(store.append(fusion))
            self.assertFalse(store.append(fusion))
            expected = store.replay()
            store.close()
            before = path.read_bytes()
            with patch.object(socket, "create_connection", side_effect=AssertionError("network used")):
                replayed = replay_lab(path)
            self.assertEqual(replayed["records"], expected)
            self.assertFalse(replayed["network_used"])
            self.assertEqual(path.read_bytes(), before)

    def test_fusion_requires_referenced_analyses_in_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite")
            fusion = create_fusion_record([launch(), liquidity()])
            with self.assertRaisesRegex(ValueError, "fusion_analysis_not_in_store"):
                store.append(fusion)
            store.close()

    def test_store_detects_fusion_chain_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite")
            source = launch()
            store.append(source)
            store.append(create_fusion_record([source]))
            store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
            store.db.execute("UPDATE lab_records SET document='{}' WHERE seq=2")
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "lab_chain_hash_mismatch"):
                store.replay()
            store.close()

    def test_reference_tampering_is_detected_even_with_rehashed_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = LabStore(Path(tmp) / "lab.sqlite")
            source = launch()
            store.append(source)
            fusion = create_fusion_record([source]).document()
            store.append(fusion)
            store.db.execute("DROP TRIGGER no_UPDATE_lab_records")
            row = store.db.execute("SELECT document,previous FROM lab_records WHERE seq=2").fetchone()
            document = json.loads(row[0])
            document["agents"]["LaunchAgentV0"]["analysis_id"] = "f" * 64
            document.pop("fusion_id")
            document["fusion_id"] = sha256_json(document)
            encoded = canonical(document)
            chain_hash = sha256_json([2, encoded, row[1]])
            store.db.execute("UPDATE lab_records SET analysis_id=?,document=?,hash=? WHERE seq=2", (document["fusion_id"], encoded, chain_hash))
            store.db.commit()
            with self.assertRaisesRegex(ValueError, "fusion_analysis_not_in_store"):
                store.replay()
            store.close()


class FusionIsolationTests(unittest.TestCase):
    def test_fusion_has_no_dependency_from_producers_or_decision_path(self):
        for path in (Path("astra_intelligence_lab/launch.py"), Path("astra_intelligence_lab/liquidity.py")):
            tree = ast.parse(path.read_text())
            modules = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            self.assertNotIn("fusion", modules)
        for base in [Path("astra"), *[p for p in Path(".").glob("astra_*") if p.is_dir() and p.name != "astra_intelligence_lab"]]:
            for path in base.glob("*.py"):
                self.assertNotIn("astra_intelligence_lab", path.read_text())

    def test_fusion_run_does_not_modify_astra_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "astra"
            (root / "state").mkdir(parents=True)
            raw = sqlite3.connect(root / "raw.sqlite")
            raw.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY,document TEXT,previous TEXT,hash TEXT)")
            for seq, kind in enumerate(("brain_decision", "position_health"), 1):
                document = canonical({"kind": kind, "metadata": {"id": kind}})
                raw.execute("INSERT INTO frames VALUES(?,?,?,?)", (seq, document, "0" * 64, sha256_json(document)))
            raw.commit(); raw.close()
            paper = sqlite3.connect(root / "state" / "paper.sqlite")
            paper.execute("CREATE TABLE ledger(seq INTEGER PRIMARY KEY,id TEXT,doc TEXT,prev TEXT,hash TEXT)")
            paper.commit(); paper.close()
            before_files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            before = capture_astra_baseline(root)
            lab_path = Path(tmp) / "lab.sqlite"
            store = LabStore(lab_path)
            source_launch = launch()
            source_liquidity = liquidity()
            store.append(source_launch)
            store.append(source_liquidity)
            store.append(create_fusion_record([source_launch, source_liquidity]))
            store.close()
            after = capture_astra_baseline(root)
            after_files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
            attestation = attest_non_influence(before, after)
            self.assertEqual(before_files, after_files)
            self.assertTrue(attestation["unchanged"])
            self.assertEqual(attestation["lab_writes_to_astra"], 0)
            self.assertFalse(attestation["network_used"])


if __name__ == "__main__":
    unittest.main()
