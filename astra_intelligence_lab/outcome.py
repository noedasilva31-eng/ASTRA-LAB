"""Historical, post-cutoff evaluation targets linked to Fusion V0 records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import assert_no_decisions, assert_unknown_is_not_zero
from .fusion import validate_fusion_record
from .integrity import sha256_json

SCHEMA = "OutcomeRecordV0"
VERSION = "OutcomeRecordV0"
HORIZON_SCHEMA = "DurationAfterCutoffV0"
MAX_TIMESTAMP_NS = 2**63 - 1
STATUSES = frozenset({"OBSERVED", "UNKNOWN", "NOT_AVAILABLE_YET", "MISSING", "INCOMPLETE_COVERAGE"})
REQUIRED_FIELDS = {
    "schema", "outcome_version", "source_fusion_id", "pool", "mint", "event_id",
    "source_cutoff_ns", "horizon", "assessment_ns", "outcome_observed_ns",
    "outcome_available_ns", "input_hashes", "provenance", "coverage", "status",
    "missing", "result", "shadow_only", "decision_effect",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _future_timestamps(value: Any, source_cutoff_ns: int, ceiling_ns: int) -> None:
    """Ensure knowledge carried by an outcome was unavailable at source cutoff."""
    time_keys = {"availability_ns", "available_at", "observed_ns", "observed_at", "decision_time", "as_of"}

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if key in time_keys and child is not None:
                    _require(
                        type(child) is int and 0 <= child <= MAX_TIMESTAMP_NS,
                        "invalid_outcome_timestamp",
                    )
                    _require(child > source_cutoff_ns, "outcome_information_not_future")
                    _require(child <= ceiling_ns, "outcome_information_after_availability")
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)


@dataclass(frozen=True)
class OutcomeRecordV0:
    source_fusion_id: str
    pool: str
    mint: str
    event_id: str
    source_cutoff_ns: int
    horizon_duration_ns: int
    assessment_ns: int
    outcome_observed_ns: int | None
    outcome_available_ns: int | None
    input_hashes: tuple[str, ...]
    provenance: tuple[Mapping[str, Any], ...]
    coverage: str
    status: str
    missing: tuple[str, ...]
    result: Any
    schema: str = SCHEMA
    outcome_version: str = VERSION
    shadow_only: bool = True
    decision_effect: str = "NONE"

    def document(self) -> dict[str, Any]:
        document = {
            "schema": self.schema,
            "outcome_version": self.outcome_version,
            "source_fusion_id": self.source_fusion_id,
            "pool": self.pool,
            "mint": self.mint,
            "event_id": self.event_id,
            "source_cutoff_ns": self.source_cutoff_ns,
            "horizon": {"schema": HORIZON_SCHEMA, "duration_ns": self.horizon_duration_ns,
                        "ends_at_ns": self.source_cutoff_ns + self.horizon_duration_ns},
            "assessment_ns": self.assessment_ns,
            "outcome_observed_ns": self.outcome_observed_ns,
            "outcome_available_ns": self.outcome_available_ns,
            "input_hashes": list(self.input_hashes),
            "provenance": list(self.provenance),
            "coverage": self.coverage,
            "status": self.status,
            "missing": list(self.missing),
            "result": self.result,
            "shadow_only": self.shadow_only,
            "decision_effect": self.decision_effect,
        }
        validate_outcome_record(document)
        document["outcome_id"] = sha256_json(document)
        return document


def create_outcome_record(fusion: Mapping[str, Any], *, horizon_duration_ns: int,
                          assessment_ns: int, outcome_observed_ns: int | None,
                          outcome_available_ns: int | None, input_hashes: Sequence[str],
                          provenance: Sequence[Mapping[str, Any]], coverage: str, status: str,
                          missing: Sequence[str], result: Any) -> OutcomeRecordV0:
    source = validate_fusion_record(fusion)
    return OutcomeRecordV0(
        source_fusion_id=source["fusion_id"], pool=source["pool"], mint=source["mint"],
        event_id=source["event_id"], source_cutoff_ns=source["cutoff_ns"],
        horizon_duration_ns=horizon_duration_ns, assessment_ns=assessment_ns,
        outcome_observed_ns=outcome_observed_ns, outcome_available_ns=outcome_available_ns,
        input_hashes=tuple(input_hashes), provenance=tuple(provenance), coverage=coverage,
        status=status, missing=tuple(missing), result=result,
    )


def validate_outcome_record(document: Mapping[str, Any],
                            fusions_by_id: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    allowed = REQUIRED_FIELDS | {"outcome_id"}
    _require(set(document) == REQUIRED_FIELDS or set(document) == allowed, "invalid_outcome_record_fields")
    _require(document["schema"] == SCHEMA and document["outcome_version"] == VERSION, "unsupported_outcome_schema")
    _require(document["shadow_only"] is True and document["decision_effect"] == "NONE", "outcome_shadow_only_required")
    for key in ("pool", "mint", "event_id", "coverage"):
        _require(isinstance(document[key], str) and bool(document[key]), "invalid_outcome_identity")
    _require(_is_sha256(document["source_fusion_id"]), "invalid_outcome_fusion_id")
    cutoff, assessment = document["source_cutoff_ns"], document["assessment_ns"]
    _require(
        type(cutoff) is int and 0 <= cutoff <= MAX_TIMESTAMP_NS,
        "invalid_outcome_source_cutoff",
    )
    _require(
        type(assessment) is int and cutoff < assessment <= MAX_TIMESTAMP_NS,
        "outcome_assessment_not_future",
    )
    horizon = document["horizon"]
    _require(isinstance(horizon, dict) and set(horizon) == {"schema", "duration_ns", "ends_at_ns"}, "invalid_outcome_horizon")
    duration = horizon.get("duration_ns")
    _require(horizon.get("schema") == HORIZON_SCHEMA and type(duration) is int and duration > 0, "invalid_outcome_horizon")
    _require(duration <= MAX_TIMESTAMP_NS - cutoff, "outcome_horizon_overflow")
    horizon_end = cutoff + duration
    _require(horizon.get("ends_at_ns") == horizon_end, "invalid_outcome_horizon_end")
    status, observed, available = document["status"], document["outcome_observed_ns"], document["outcome_available_ns"]
    _require(status in STATUSES, "invalid_outcome_status")
    if status == "NOT_AVAILABLE_YET":
        _require(assessment < horizon_end, "outcome_horizon_already_elapsed")
        _require(observed is None and available is None and document["result"] is None, "premature_outcome_value")
    else:
        _require(assessment >= horizon_end, "outcome_horizon_not_complete")
        if status in {"OBSERVED", "INCOMPLETE_COVERAGE"}:
            _require(type(observed) is int and observed >= horizon_end, "outcome_observed_before_horizon")
            _require(type(available) is int and available >= observed, "invalid_outcome_availability")
            _require(document["result"] is not None, "observed_outcome_requires_result")
        else:
            _require(observed is None and available is None and document["result"] is None, "absent_outcome_requires_null")
    if available is not None:
        _require(available > cutoff and available <= assessment, "invalid_outcome_availability")
    missing = document["missing"]
    _require(isinstance(missing, list) and all(isinstance(v, str) and v for v in missing), "invalid_outcome_missing")
    provenance = document["provenance"]
    _require(isinstance(provenance, list), "invalid_outcome_provenance")
    if status == "OBSERVED":
        _require(document["coverage"] == "COMPLETE" and not missing, "observed_outcome_must_be_complete")
        _require(bool(provenance), "observed_outcome_requires_provenance")
    else:
        _require(bool(missing), "non_observed_outcome_requires_missing")
        _require(document["coverage"] != "COMPLETE", "non_observed_outcome_cannot_be_complete")
        if status == "INCOMPLETE_COVERAGE":
            _require(bool(provenance), "incomplete_outcome_requires_provenance")
    _require(isinstance(document["input_hashes"], list) and bool(document["input_hashes"])
             and all(_is_sha256(v) for v in document["input_hashes"]), "invalid_outcome_input_hashes")
    ceiling = available if available is not None else assessment
    _future_timestamps(provenance, cutoff, ceiling)
    _future_timestamps(document["result"], cutoff, ceiling)
    assert_no_decisions(document)
    assert_unknown_is_not_zero(document)
    if fusions_by_id is not None:
        fusion_id = document["source_fusion_id"]
        _require(fusion_id in fusions_by_id, "outcome_fusion_not_in_store")
        fusion = validate_fusion_record(fusions_by_id[fusion_id])
        _require((fusion["pool"], fusion["mint"], fusion["event_id"], fusion["cutoff_ns"])
                 == (document["pool"], document["mint"], document["event_id"], cutoff),
                 "outcome_fusion_context_mismatch")
    expected = sha256_json({key: document[key] for key in REQUIRED_FIELDS})
    if "outcome_id" in document:
        _require(document["outcome_id"] == expected, "outcome_hash_mismatch")
    return dict(document)
