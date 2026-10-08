import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from astra_intelligence_lab.flow import observations_available_at, validate_flow_observation
from astra_intelligence_lab.flow_archive import (
    FlowArchiveImporterV0,
    _observation_order_key,
    create_flow_freeze,
    verify_flow_freeze,
)
from astra_intelligence_lab.integrity import canonical, sha256_file, sha256_json
from astra_intelligence_lab.store_v1 import IncrementalLabStoreV1

SOURCE = Path("position_handoff/offline-resume/state/engine.sqlite")


def make_freeze(root):
    importer = FlowArchiveImporterV0(SOURCE)
    observations, coverage = importer.read_observations()
    store_path = root / "store.sqlite"
    store = IncrementalLabStoreV1(store_path)
    importer.import_into(store)
    store.close()
    manifest = create_flow_freeze(root / "freeze", store_path, coverage, [SOURCE])
    return observations, coverage, manifest, root / "freeze"


def rehash_manifest(path, mutate):
    document = json.loads(path.read_text())
    document.pop("freeze_id")
    mutate(document)
    document["freeze_id"] = sha256_json(document)
    path.write_text(canonical(document))


class FlowImportSemanticsAuditTests(unittest.TestCase):
    def test_every_imported_field_is_a_direct_source_projection(self):
        observations, _ = FlowArchiveImporterV0(SOURCE).read_observations()
        database = sqlite3.connect(SOURCE.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        try:
            events = {row[0]: json.loads(row[1]) for row in database.execute("SELECT id,document FROM events")}
        finally:
            database.close()
        for observation in observations:
            event = events[observation["event_id"]]
            self.assertEqual(observation["pool"], event["pool"])
            self.assertEqual(observation["mint"], event["base_mint"])
            self.assertEqual(observation["wallets"], {"user": event["wallet"]})
            for key in ("signature", "slot", "instruction_index", "inner_instruction_index", "event_time", "availability_ns"):
                self.assertEqual(observation[key], event.get(key))
            for key in ("input_mint", "output_mint", "base_mint", "quote_mint", "input_amount_raw", "output_amount_raw",
                        "instruction", "event_type", "commitment", "network"):
                self.assertEqual(observation["values"][key], event[key])
            self.assertEqual(observation["values"]["canonical_fields"], event["fields"])
            self.assertIsNone(observation["observed_ns"])
            self.assertIn("observed_ns", observation["missing_dimensions"])

    def test_observation_identity_covers_every_semantic_dimension(self):
        original = FlowArchiveImporterV0(SOURCE).read_observations()[0][0]
        body = copy.deepcopy(original); body.pop("observation_id")
        mutations = {
            "availability": lambda value: value.__setitem__("availability_ns", value["availability_ns"] + 1),
            "signature": lambda value: value.__setitem__("signature", "other"),
            "slot": lambda value: value.__setitem__("slot", value["slot"] + 1),
            "pool": lambda value: value.__setitem__("pool", "other"),
            "mint": lambda value: value.__setitem__("mint", "other"),
            "wallet": lambda value: value["wallets"].__setitem__("user", "other"),
            "event": lambda value: value.__setitem__("event_id", "f" * 64),
            "amount": lambda value: value["values"].__setitem__("input_amount_raw", "999"),
            "provenance": lambda value: value["provenance"].__setitem__("source_sequence", 999),
            "source_hash": lambda value: value.__setitem__("source_hashes", ["f" * 64]),
            "missing": lambda value: value.__setitem__("missing_dimensions", ["observed_ns", "wallets"]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                changed = copy.deepcopy(body); mutate(changed)
                self.assertNotEqual(original["observation_id"], sha256_json(changed))

    def test_new_process_timezone_locale_and_physical_row_order_are_irrelevant(self):
        expected = FlowArchiveImporterV0(SOURCE).read_observations()[0][0]["observation_id"]
        script = (
            "from astra_intelligence_lab.flow_archive import FlowArchiveImporterV0;"
            "print(FlowArchiveImporterV0('position_handoff/offline-resume/state/engine.sqlite')"
            ".read_observations()[0][0]['observation_id'])"
        )
        values = []
        for timezone in ("UTC", "Pacific/Honolulu"):
            result = subprocess.run(
                [sys.executable, "-B", "-c", script], cwd=Path(__file__).resolve().parents[1],
                env=dict(os.environ, TZ=timezone, LC_ALL="C", PYTHONDONTWRITEBYTECODE="1"),
                text=True, capture_output=True, check=True, timeout=30,
            )
            values.append(result.stdout.strip())
        self.assertEqual(values, [expected, expected])
        importer = FlowArchiveImporterV0(SOURCE)
        database = sqlite3.connect(SOURCE.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        rows = database.execute("SELECT seq,id,document,hash,semantic FROM events").fetchall(); database.close()
        forward = sorted([importer._convert_row(row, sha256_file(SOURCE)) for row in rows], key=_observation_order_key)
        reverse = sorted([importer._convert_row(row, sha256_file(SOURCE)) for row in reversed(rows)], key=_observation_order_key)
        self.assertEqual(forward, reverse)

    def test_canonical_order_is_total_under_adversarial_ties(self):
        first = FlowArchiveImporterV0(SOURCE).read_observations()[0][0]
        values = []
        for event_id, inner in (("b", None), ("a", None), ("a", 0)):
            item = copy.deepcopy(first)
            item.update(event_id=event_id, inner_instruction_index=inner)
            item.pop("observation_id"); item["observation_id"] = sha256_json(item)
            values.append(item)
        ordered = sorted(reversed(values), key=_observation_order_key)
        self.assertEqual(ordered, sorted(values, key=_observation_order_key))
        self.assertEqual(len({_observation_order_key(item) for item in values}), 3)


class FlowFreezeFinalAuditTests(unittest.TestCase):
    def test_every_manifest_dimension_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, manifest, _ = make_freeze(Path(tmp))
            original = manifest["freeze_id"]
            body = copy.deepcopy(manifest); body.pop("freeze_id")
            mutations = {
                "sources": lambda value: value["source_identities"][0].__setitem__("source_schema", "other"),
                "ordered_ids": lambda value: value["ordered_observation_ids"].reverse(),
                "count": lambda value: value.__setitem__("record_count", 50),
                "first": lambda value: value.__setitem__("first_availability_ns", 0),
                "last": lambda value: value.__setitem__("last_availability_ns", 0),
                "cutoff": lambda value: value["cutoff_range"].__setitem__("minimum_ns", 0),
                "schema": lambda value: value.__setitem__("store_schema", "other"),
                "head": lambda value: value.__setitem__("store_head_hash", "0" * 64),
                "coverage": lambda value: value.__setitem__("coverage_report_hash", "0" * 64),
                "files": lambda value: value["files"].__setitem__("coverage.json", "0" * 64),
                "flags": lambda value: value.__setitem__("shadow_only", False),
            }
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    changed = copy.deepcopy(body); mutate(changed)
                    self.assertNotEqual(original, sha256_json(changed))

    def test_recomputed_manifest_cannot_lie_about_bounds_flags_sources_or_paths(self):
        mutations = {
            "bounds": lambda value: value.__setitem__("first_availability_ns", 0),
            "cutoff": lambda value: value.__setitem__("cutoff_range", {"minimum_ns": 0, "maximum_ns": 1}),
            "flag": lambda value: value.__setitem__("decision_effect", "OTHER"),
            "source": lambda value: value["source_identities"][0].__setitem__("source_sha256", "f" * 64),
            "duplicate_source": lambda value: value["source_identities"].append(copy.deepcopy(value["source_identities"][0])),
            "path": lambda value: value["files"].__setitem__("../outside", "0" * 64),
            "extra_field": lambda value: value.__setitem__("unexpected", True),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                _, _, _, freeze = make_freeze(Path(tmp))
                rehash_manifest(freeze / "manifest.json", mutate)
                with self.assertRaises(ValueError): verify_flow_freeze(freeze)

    def test_json_key_order_is_irrelevant_but_duplicate_keys_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, manifest, freeze = make_freeze(Path(tmp))
            reordered = {key: manifest[key] for key in reversed(manifest)}
            (freeze / "manifest.json").write_text(json.dumps(reordered, separators=(",", ":")))
            self.assertEqual(verify_flow_freeze(freeze)["freeze_id"], manifest["freeze_id"])
            encoded = (freeze / "manifest.json").read_text()
            (freeze / "manifest.json").write_text(encoded[:-1] + ',"schema":"FlowFreezeManifestV0"}')
            with self.assertRaisesRegex(ValueError, "flow_freeze_duplicate_json_key"):
                verify_flow_freeze(freeze)

    def test_fully_rehashed_store_falsification_is_rejected_against_frozen_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, _, freeze = make_freeze(Path(tmp))
            store_path = freeze / "flow-store-v1.sqlite"
            database = sqlite3.connect(store_path)
            database.execute("DROP TRIGGER no_UPDATE_lab_records")
            rows = database.execute("SELECT seq,document FROM lab_records ORDER BY seq").fetchall()
            previous = "0" * 64; identities = []
            for seq, encoded in rows:
                document = json.loads(encoded)
                if seq == 1:
                    document["values"]["input_amount_raw"] = "999"
                    document.pop("observation_id")
                    document["observation_id"] = sha256_json(document)
                encoded = canonical(document); digest = sha256_json([seq, encoded, previous])
                database.execute(
                    "UPDATE lab_records SET identity=?,document=?,previous=?,hash=? WHERE seq=?",
                    (document["observation_id"], encoded, previous, digest, seq),
                )
                identities.append(document["observation_id"]); previous = digest
            database.execute("UPDATE lab_head SET hash=?", (previous,)); database.commit(); database.close()
            def rewrite(manifest):
                manifest["ordered_observation_ids"] = identities
                manifest["store_head_hash"] = previous
                manifest["files"]["flow-store-v1.sqlite"] = sha256_file(store_path)
            rehash_manifest(freeze / "manifest.json", rewrite)
            with self.assertRaisesRegex(ValueError, "flow_freeze_source_projection_mismatch"):
                verify_flow_freeze(freeze)


class FlowCutoffBoundaryAuditTests(unittest.TestCase):
    def test_cutoff_uses_only_availability_and_never_coerces_missing_observed(self):
        observations, _ = FlowArchiveImporterV0(SOURCE).read_observations()
        altered = copy.deepcopy(observations[0])
        altered["event_time"] = 2**63 - 1
        altered.pop("observation_id"); altered["observation_id"] = sha256_json(altered)
        cutoff = altered["availability_ns"]
        self.assertEqual(observations_available_at([altered], cutoff - 1), [])
        selected = observations_available_at([altered], cutoff)
        self.assertEqual(len(selected), 1)
        self.assertIsNone(selected[0]["observed_ns"])
        self.assertNotEqual(selected[0]["observed_ns"], 0)


if __name__ == "__main__":
    unittest.main()
