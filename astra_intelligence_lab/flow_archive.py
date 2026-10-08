"""Offline-only importer and freeze/replay utilities for canonical Flow V0 facts."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .flow import FlowObservationV0, SCHEMA as FLOW_SCHEMA, observations_available_at
from .integrity import canonical, sha256_file, sha256_json
from .store_v1 import IncrementalLabStoreV1, STORE_SCHEMA

IMPORTER_VERSION = "FlowArchiveImporterV0"
FREEZE_VERSION = "FlowFreezeManifestV0"
COVERAGE_VERSION = "FlowCoverageReportV0"
REFERENCE_SOURCE_SHA256 = "d61646d3c37a9a60af10b65ffab3c6aa512bef1ab188d4ef1d8675e7fc597b7f"
REQUIRED_EVENT_FIELDS = {
    "availability_ns", "base_mint", "commitment", "event_data_sha256", "event_time",
    "event_type", "fields", "id", "input_amount_raw", "input_mint", "instruction",
    "instruction_index", "kind", "network", "output_amount_raw", "output_mint", "pool",
    "protocol", "provenance", "quote_mint", "signature", "slot", "wallet",
}
MANIFEST_FIELDS = {
    "schema", "freeze_version", "store_schema", "source_identities",
    "ordered_observation_ids", "record_count", "first_availability_ns",
    "last_availability_ns", "cutoff_range", "store_head_hash",
    "coverage_report_hash", "files", "network_used", "lab_writes_to_astra",
    "shadow_only", "decision_effect", "freeze_id",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _write_once(path: Path, document: Mapping[str, Any], conflict: str) -> None:
    encoded = canonical(document)
    if path.exists():
        _require(path.read_text(encoding="utf-8") == encoded, conflict)
    else:
        path.write_text(encoded, encoding="utf-8")


def _load_json_strict(path: Path) -> dict[str, Any]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, "flow_freeze_duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=object_pairs)
    _require(isinstance(value, dict), "flow_freeze_document_not_object")
    return value


def _safe_freeze_name(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).name == value and value not in {".", ".."}


def _observation_order_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        item["availability_ns"],
        item["slot"] if item["slot"] is not None else -1,
        item["signature"] or "",
        item["instruction_index"] if item["instruction_index"] is not None else -1,
        item["inner_instruction_index"] if item["inner_instruction_index"] is not None else -1,
        item["event_id"] or "",
        item["observation_id"],
    )


class FlowArchiveImporterV0:
    def __init__(self, source: str | Path, expected_sha256: str = REFERENCE_SOURCE_SHA256):
        self.source = Path(source)
        self.expected_sha256 = expected_sha256

    def read_observations(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        _require(self.source.is_file(), "flow_source_missing")
        before = sha256_file(self.source)
        _require(before == self.expected_sha256, "flow_source_hash_mismatch")
        database = sqlite3.connect(
            self.source.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            columns = [row[1] for row in database.execute("PRAGMA table_info(events)")]
            _require(columns == ["seq", "id", "document", "hash", "semantic"], "unsupported_flow_source_schema")
            rows = database.execute("SELECT seq,id,document,hash,semantic FROM events").fetchall()
        finally:
            database.close()
        _require(sha256_file(self.source) == before, "flow_source_changed_during_import")
        observations = [self._convert_row(row, before) for row in rows]
        identities = [item["observation_id"] for item in observations]
        event_ids = [item["event_id"] for item in observations]
        _require(len(identities) == len(set(identities)), "duplicate_flow_observation")
        _require(len(event_ids) == len(set(event_ids)), "duplicate_flow_event")
        observations.sort(key=_observation_order_key)
        coverage = build_flow_coverage_report(observations, before)
        return observations, coverage

    def _convert_row(self, row: tuple[Any, ...], source_hash: str) -> dict[str, Any]:
        seq, row_id, encoded, row_hash, semantic_hash = row
        event = json.loads(encoded)
        _require(sha256_json(event) == row_hash, "canonical_event_row_hash_mismatch")
        semantic_event = {
            key: value
            for key, value in event.items()
            if key not in {"availability_ns", "provenance", "commitment"}
        }
        _require(
            sha256_json(semantic_event) == semantic_hash,
            "canonical_event_semantic_hash_mismatch",
        )
        _require(event.get("id") == row_id, "canonical_event_identity_mismatch")
        _require(REQUIRED_EVENT_FIELDS <= set(event), "canonical_event_fields_missing")
        _require(event["kind"] == "swap", "unsupported_canonical_event_kind")
        _require(event["protocol"] == "pumpswap", "unsupported_canonical_event_protocol")
        source_hashes = {
            source_hash,
            row_hash,
            event["event_data_sha256"],
            *[value for key, value in event["provenance"].items() if key.endswith("sha256")],
        }
        missing = ["observed_ns"]
        if event.get("inner_instruction_index") is None:
            missing.append("inner_instruction_index")
        observation = FlowObservationV0(
            observation_type="SWAP",
            pool=event["pool"],
            mint=event["base_mint"],
            wallets={"user": event["wallet"]},
            signature=event["signature"],
            slot=event["slot"],
            event_id=event["id"],
            instruction_index=event["instruction_index"],
            inner_instruction_index=event.get("inner_instruction_index"),
            event_time=event["event_time"],
            observed_ns=None,
            availability_ns=event["availability_ns"],
            source_hashes=tuple(sorted(source_hashes)),
            provenance={
                "importer_version": IMPORTER_VERSION,
                "source_schema": "AstraEngineEventsArchive",
                "source_sha256": source_hash,
                "source_sequence": seq,
                "source_row_sha256": row_hash,
                "source_semantic_sha256": semantic_hash,
                "event_provenance": event["provenance"],
            },
            values={
                "instruction": event["instruction"],
                "event_type": event["event_type"],
                "commitment": event["commitment"],
                "network": event["network"],
                "input_mint": event["input_mint"],
                "output_mint": event["output_mint"],
                "base_mint": event["base_mint"],
                "quote_mint": event["quote_mint"],
                "input_amount_raw": event["input_amount_raw"],
                "output_amount_raw": event["output_amount_raw"],
                "canonical_fields": event["fields"],
            },
            coverage="CANONICAL_ACCEPTED_SWAP_OBSERVED_SUBSET",
            missing_dimensions=tuple(missing),
        )
        return observation.document()

    def import_into(self, store: IncrementalLabStoreV1) -> dict[str, Any]:
        observations, coverage = self.read_observations()
        appended = sum(1 for observation in observations if store.append(observation))
        return {
            "schema": "FlowArchiveImportReceiptV0",
            "importer_version": IMPORTER_VERSION,
            "source_sha256": self.expected_sha256,
            "observations": len(observations),
            "appended": appended,
            "redelivered": len(observations) - appended,
            "coverage_report_id": coverage["coverage_report_id"],
            "network_used": False,
            "lab_writes_to_astra": 0,
            "shadow_only": True,
            "decision_effect": "NONE",
        }


def build_flow_coverage_report(
    observations: list[Mapping[str, Any]], source_sha256: str
) -> dict[str, Any]:
    missing = Counter(
        dimension for observation in observations for dimension in observation["missing_dimensions"]
    )
    availabilities = [item["availability_ns"] for item in observations]
    slots = [item["slot"] for item in observations if item["slot"] is not None]
    document = {
        "schema": COVERAGE_VERSION,
        "coverage_version": COVERAGE_VERSION,
        "source_sha256": source_sha256,
        "source_events": len(observations),
        "observations_produced": len(observations),
        "distinct_pools": len({item["pool"] for item in observations}),
        "distinct_mints": len({item["mint"] for item in observations}),
        "distinct_wallets": len({wallet for item in observations for wallet in item["wallets"].values()}),
        "slot_min": min(slots) if slots else None,
        "slot_max": max(slots) if slots else None,
        "availability_min_ns": min(availabilities) if availabilities else None,
        "availability_max_ns": max(availabilities) if availabilities else None,
        "missing_dimensions": dict(sorted(missing.items())),
        "families": {
            "canonical_accepted_swaps": "SUPPORTED",
            "complete_market_activity": "PARTIAL",
            "generic_transfers": "UNSUPPORTED",
            "generic_balances": "UNSUPPORTED",
            "concentration_holders": "UNSUPPORTED",
            "reorganizations": "UNKNOWN",
            "rejected_pumpswap_layouts": "BLOCKED",
        },
        "limitations": [
            "51 canonical swaps do not represent the complete market",
            "absence of an observation is not evidence of absence of activity",
            "observed_ns is unavailable in the canonical events and remains null",
            "BLOCKED_ON_DEPLOYED_LAYOUT_DEFINITION",
        ],
        "shadow_only": True,
        "decision_effect": "NONE",
    }
    document["coverage_report_id"] = sha256_json(document)
    return document


def create_flow_freeze(
    directory: str | Path,
    store_path: str | Path,
    coverage: Mapping[str, Any],
    source_files: list[str | Path],
) -> dict[str, Any]:
    target = Path(directory)
    _require(not target.exists() or not any(target.iterdir()), "flow_freeze_directory_not_empty")
    target.mkdir(parents=True, exist_ok=True)
    store_source = Path(store_path)
    store_before = sha256_file(store_source)
    store = IncrementalLabStoreV1(store_source, readonly=True)
    try:
        records = store.replay()
        audit = store.audit()
    finally:
        store.close()
    _require(sha256_file(store_source) == store_before, "flow_store_changed_during_freeze")
    _require(bool(records) and all(item["schema"] == FLOW_SCHEMA for item in records), "flow_freeze_requires_flow_only_store")
    _require(
        build_flow_coverage_report(records, coverage.get("source_sha256")) == dict(coverage),
        "flow_coverage_content_mismatch",
    )
    expected_coverage = dict(coverage)
    coverage_id = expected_coverage.pop("coverage_report_id", None)
    _require(sha256_json(expected_coverage) == coverage_id, "flow_coverage_hash_mismatch")
    store_target = target / "flow-store-v1.sqlite"
    coverage_target = target / "coverage.json"
    shutil.copyfile(store_source, store_target)
    _write_once(coverage_target, coverage, "flow_coverage_identity_conflict")
    frozen_sources = []
    unique_sources: dict[str, Path] = {}
    for source in (Path(item) for item in source_files):
        unique_sources.setdefault(sha256_file(source), source)
    for index, (digest, source) in enumerate(sorted(unique_sources.items())):
        frozen_name = f"source-{index}-{source.name}"
        shutil.copyfile(source, target / frozen_name)
        _require(sha256_file(source) == digest, "flow_source_changed_during_freeze")
        frozen_sources.append({
            "source_schema": "AstraEngineEventsArchive",
            "source_sha256": digest,
            "freeze_file": frozen_name,
        })
    _require(
        coverage["source_sha256"] in {item["source_sha256"] for item in frozen_sources},
        "flow_coverage_source_missing",
    )
    ordered_ids = [item["observation_id"] for item in records]
    availabilities = [item["availability_ns"] for item in records]
    manifest = {
        "schema": FREEZE_VERSION,
        "freeze_version": FREEZE_VERSION,
        "store_schema": STORE_SCHEMA,
        "source_identities": frozen_sources,
        "ordered_observation_ids": ordered_ids,
        "record_count": len(records),
        "first_availability_ns": min(availabilities),
        "last_availability_ns": max(availabilities),
        "cutoff_range": {"minimum_ns": min(availabilities), "maximum_ns": max(availabilities)},
        "store_head_hash": audit["head"],
        "coverage_report_hash": coverage_id,
        "files": {
            store_target.name: sha256_file(store_target),
            coverage_target.name: sha256_file(coverage_target),
            **{item["freeze_file"]: item["source_sha256"] for item in frozen_sources},
        },
        "network_used": False,
        "lab_writes_to_astra": 0,
        "shadow_only": True,
        "decision_effect": "NONE",
    }
    manifest["freeze_id"] = sha256_json(manifest)
    _write_once(target / "manifest.json", manifest, "flow_freeze_identity_conflict")
    return manifest


def verify_flow_freeze(directory: str | Path, cutoff_ns: int | None = None) -> dict[str, Any]:
    root = Path(directory)
    manifest_path = root / "manifest.json"
    _require(manifest_path.is_file(), "flow_freeze_manifest_missing")
    manifest = _load_json_strict(manifest_path)
    _require(set(manifest) == MANIFEST_FIELDS, "invalid_flow_freeze_manifest_fields")
    freeze_id = manifest.pop("freeze_id", None)
    _require(
        manifest.get("schema") == FREEZE_VERSION
        and manifest.get("freeze_version") == FREEZE_VERSION
        and manifest.get("store_schema") == STORE_SCHEMA,
        "unsupported_flow_freeze",
    )
    _require(
        manifest.get("network_used") is False
        and manifest.get("lab_writes_to_astra") == 0
        and manifest.get("shadow_only") is True
        and manifest.get("decision_effect") == "NONE",
        "invalid_flow_freeze_shadow_flags",
    )
    _require(sha256_json(manifest) == freeze_id, "flow_freeze_hash_mismatch")
    _require(
        isinstance(manifest.get("files"), dict)
        and all(_safe_freeze_name(name) for name in manifest["files"]),
        "flow_freeze_path_invalid",
    )
    expected_files = set(manifest["files"]) | {"manifest.json"}
    actual_files = {path.name for path in root.iterdir() if path.is_file()}
    _require(actual_files == expected_files, "flow_freeze_file_set_mismatch")
    for name, digest in manifest["files"].items():
        _require(sha256_file(root / name) == digest, "flow_freeze_file_hash_mismatch")
    sources = manifest.get("source_identities")
    _require(isinstance(sources, list) and len(sources) == 1, "invalid_flow_freeze_sources")
    _require(
        len({source.get("freeze_file") for source in sources if isinstance(source, dict)}) == len(sources),
        "duplicate_flow_freeze_source",
    )
    for source in sources:
        _require(
            isinstance(source, dict)
            and set(source) == {"source_schema", "source_sha256", "freeze_file"}
            and source["source_schema"] == "AstraEngineEventsArchive"
            and source["source_sha256"] == REFERENCE_SOURCE_SHA256
            and _safe_freeze_name(source["freeze_file"]),
            "invalid_flow_freeze_source_identity",
        )
        _require(
            manifest["files"].get(source["freeze_file"]) == source["source_sha256"],
            "flow_freeze_source_identity_mismatch",
        )
    coverage = _load_json_strict(root / "coverage.json")
    coverage_body = dict(coverage)
    coverage_id = coverage_body.pop("coverage_report_id", None)
    _require(sha256_json(coverage_body) == coverage_id, "flow_coverage_hash_mismatch")
    _require(coverage_id == manifest["coverage_report_hash"], "flow_coverage_manifest_mismatch")
    store = IncrementalLabStoreV1(root / "flow-store-v1.sqlite", readonly=True)
    try:
        records = store.replay()
        audit = store.audit()
    finally:
        store.close()
    _require(len(records) == manifest["record_count"], "flow_freeze_record_count_mismatch")
    _require([item["observation_id"] for item in records] == manifest["ordered_observation_ids"], "flow_freeze_order_mismatch")
    _require(audit["head"] == manifest["store_head_hash"], "flow_freeze_head_mismatch")
    availabilities = [item["availability_ns"] for item in records]
    _require(
        bool(availabilities)
        and manifest["first_availability_ns"] == min(availabilities)
        and manifest["last_availability_ns"] == max(availabilities)
        and manifest["cutoff_range"] == {
            "minimum_ns": min(availabilities), "maximum_ns": max(availabilities)
        },
        "flow_freeze_availability_bounds_mismatch",
    )
    reconstructed, reconstructed_coverage = FlowArchiveImporterV0(
        root / sources[0]["freeze_file"], REFERENCE_SOURCE_SHA256
    ).read_observations()
    _require(records == reconstructed, "flow_freeze_source_projection_mismatch")
    _require(coverage == reconstructed_coverage, "flow_freeze_coverage_projection_mismatch")
    selected = records if cutoff_ns is None else observations_available_at(records, cutoff_ns)
    return {
        "schema": "FlowFreezeReplayV0",
        "freeze_id": freeze_id,
        "cutoff_ns": cutoff_ns,
        "observations": selected,
        "observation_ids": [item["observation_id"] for item in selected],
        "records_sha256": sha256_json(selected),
        "coverage_report_id": coverage_id,
        "network_used": False,
        "lab_writes_to_astra": 0,
        "shadow_only": True,
        "decision_effect": "NONE",
    }
