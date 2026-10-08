"""Self-contained SHADOW contracts. This module has no ASTRA runtime imports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .integrity import sha256_json

SCHEMA = "ShadowAnalysisEnvelopeV0"
FORBIDDEN_DECISIONS = frozenset(
    {"BUY", "SELL", "HOLD", "CANDIDATE_BUY", "EXIT_CANDIDATE"}
)
CLASSIFICATIONS = frozenset({"OBSERVED", "DERIVED", "UNKNOWN"})


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _walk(value: Any):
    yield value
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk(item)


def assert_no_decisions(value: Any) -> None:
    for item in _walk(value):
        if isinstance(item, str) and item.upper() in FORBIDDEN_DECISIONS:
            raise ValueError("shadow_decision_forbidden")


def assert_cutoff(value: Any, cutoff_ns: int) -> None:
    """Reject knowledge timestamps later than the declared analysis cutoff."""
    time_keys = {
        "availability_ns",
        "available_at",
        "observed_ns",
        "decision_time",
        "as_of",
    }

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if key in time_keys and child is not None:
                    _require(type(child) is int and child >= 0, "invalid_knowledge_timestamp")
                    _require(child <= cutoff_ns, "shadow_future_information")
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)


def assert_unknown_is_not_zero(value: Any) -> None:
    """UNKNOWN values remain null; absence must never be represented as numeric zero."""
    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            status = item.get("status", item.get("classification"))
            if status == "UNKNOWN" and "value" in item:
                _require(item["value"] is None, "unknown_must_be_null")
            for child in item.values():
                visit(child)
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            for child in item:
                visit(child)

    visit(value)


@dataclass(frozen=True)
class ShadowAnalysisEnvelopeV0:
    agent: str
    agent_version: str
    event_id: str
    pool: str
    mint: str
    cutoff_ns: int
    input_hashes: tuple[str, ...]
    provenance: tuple[Mapping[str, Any], ...]
    coverage: str
    classification: str
    missing: tuple[str, ...]
    result: Any
    schema: str = SCHEMA
    shadow_only: bool = True

    def document(self) -> dict[str, Any]:
        document = asdict(self)
        document["input_hashes"] = list(self.input_hashes)
        document["provenance"] = list(self.provenance)
        document["missing"] = list(self.missing)
        validate_envelope(document)
        document["analysis_id"] = sha256_json(document)
        return document


def validate_envelope(document: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "agent",
        "agent_version",
        "event_id",
        "pool",
        "mint",
        "cutoff_ns",
        "input_hashes",
        "provenance",
        "coverage",
        "classification",
        "missing",
        "result",
        "shadow_only",
    }
    allowed = required | {"analysis_id"}
    _require(set(document) == required or set(document) == allowed, "invalid_shadow_envelope_fields")
    _require(document["schema"] == SCHEMA, "unsupported_shadow_schema")
    _require(document["shadow_only"] is True, "shadow_only_required")
    for key in ("agent", "agent_version", "event_id", "pool", "mint", "coverage"):
        _require(isinstance(document[key], str) and bool(document[key]), "invalid_shadow_identity")
    _require(type(document["cutoff_ns"]) is int and document["cutoff_ns"] >= 0, "invalid_cutoff")
    _require(document["classification"] in CLASSIFICATIONS, "invalid_shadow_classification")
    _require(
        isinstance(document["input_hashes"], list)
        and bool(document["input_hashes"])
        and all(isinstance(v, str) and len(v) == 64 for v in document["input_hashes"]),
        "invalid_input_hashes",
    )
    _require(isinstance(document["provenance"], list), "invalid_shadow_provenance")
    _require(
        isinstance(document["missing"], list)
        and all(isinstance(v, str) and v for v in document["missing"]),
        "invalid_missing_dimensions",
    )
    if document["classification"] == "UNKNOWN":
        _require(document["result"] is None and bool(document["missing"]), "unknown_requires_null_and_missing")
    assert_no_decisions(document)
    assert_cutoff(document["provenance"], document["cutoff_ns"])
    assert_cutoff(document["result"], document["cutoff_ns"])
    assert_unknown_is_not_zero(document)
    expected = sha256_json({k: document[k] for k in required})
    if "analysis_id" in document:
        _require(document["analysis_id"] == expected, "shadow_analysis_hash_mismatch")
    return dict(document)
