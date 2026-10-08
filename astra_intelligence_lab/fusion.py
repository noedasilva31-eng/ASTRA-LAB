"""Non-decision recorder aligning existing SHADOW analyses at one exact cutoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import assert_cutoff, assert_no_decisions, assert_unknown_is_not_zero, validate_envelope
from .integrity import sha256_json

SCHEMA = "AgentFusionRecordV0"
VERSION = "AgentFusionRecorderV0"
TEMPORAL_RULE = "EXACT_IDENTITY_AND_CUTOFF_V0"
SUPPORTED_PRODUCERS = ("LaunchAgentV0", "LiquidityAgentV0")
PRESENT_REFERENCE_FIELDS = {
    "status",
    "agent_version",
    "analysis_id",
    "cutoff_ns",
    "input_hashes",
    "provenance",
    "coverage",
    "missing",
    "classification",
    "shadow_only",
}


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _document(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    document = value.document() if hasattr(value, "document") else dict(value)
    return validate_envelope(document)


def _present_reference(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": "PRESENT",
        "agent_version": envelope["agent_version"],
        "analysis_id": envelope["analysis_id"],
        "cutoff_ns": envelope["cutoff_ns"],
        "input_hashes": list(envelope["input_hashes"]),
        "provenance": list(envelope["provenance"]),
        "coverage": envelope["coverage"],
        "missing": list(envelope["missing"]),
        "classification": envelope["classification"],
        "shadow_only": True,
    }


def _missing_reference() -> dict[str, Any]:
    return {
        "status": "MISSING",
        "agent_version": None,
        "analysis_id": None,
        "cutoff_ns": None,
        "input_hashes": [],
        "provenance": [],
        "coverage": "UNKNOWN",
        "missing": ["agent_analysis"],
        "classification": "UNKNOWN",
        "shadow_only": True,
    }


@dataclass(frozen=True)
class AgentFusionRecordV0:
    pool: str
    mint: str
    event_id: str
    cutoff_ns: int
    agents: Mapping[str, Mapping[str, Any]]
    schema: str = SCHEMA
    fusion_version: str = VERSION
    temporal_rule: str = TEMPORAL_RULE
    shadow_only: bool = True
    decision_effect: str = "NONE"

    def document(self) -> dict[str, Any]:
        agents = {name: dict(self.agents[name]) for name in sorted(self.agents)}
        document = {
            "schema": self.schema,
            "fusion_version": self.fusion_version,
            "pool": self.pool,
            "mint": self.mint,
            "event_id": self.event_id,
            "cutoff_ns": self.cutoff_ns,
            "temporal_rule": self.temporal_rule,
            "supported_producers": list(SUPPORTED_PRODUCERS),
            "present_agents": [name for name in SUPPORTED_PRODUCERS if agents[name]["status"] == "PRESENT"],
            "missing_agents": [name for name in SUPPORTED_PRODUCERS if agents[name]["status"] == "MISSING"],
            "agents": agents,
            "shadow_only": self.shadow_only,
            "decision_effect": self.decision_effect,
        }
        validate_fusion_record(document)
        document["fusion_id"] = sha256_json(document)
        return document


def create_fusion_record(
    analyses: Sequence[Mapping[str, Any] | Any],
    *,
    cutoff_ns: int | None = None,
) -> AgentFusionRecordV0:
    """Align supported analyses; all present producers must share identity and cutoff."""
    documents = [_document(value) for value in analyses]
    _require(bool(documents), "fusion_requires_present_analysis")
    by_agent: dict[str, dict[str, Any]] = {}
    for document in documents:
        agent = document["agent"]
        _require(agent in SUPPORTED_PRODUCERS, "unsupported_fusion_producer")
        _require(agent not in by_agent, "duplicate_fusion_producer")
        by_agent[agent] = document
    anchor = documents[0]
    expected_cutoff = anchor["cutoff_ns"] if cutoff_ns is None else cutoff_ns
    _require(type(expected_cutoff) is int and expected_cutoff >= 0, "invalid_fusion_cutoff")
    for document in documents:
        _require(
            (document["pool"], document["mint"], document["event_id"])
            == (anchor["pool"], anchor["mint"], anchor["event_id"]),
            "fusion_context_mismatch",
        )
        _require(document["cutoff_ns"] == expected_cutoff, "fusion_cutoff_mismatch")
    agents = {
        name: _present_reference(by_agent[name]) if name in by_agent else _missing_reference()
        for name in SUPPORTED_PRODUCERS
    }
    return AgentFusionRecordV0(
        pool=anchor["pool"],
        mint=anchor["mint"],
        event_id=anchor["event_id"],
        cutoff_ns=expected_cutoff,
        agents=agents,
    )


def _assert_reference_matches(reference: Mapping[str, Any], envelope: Mapping[str, Any]) -> None:
    expected = _present_reference(envelope)
    _require(dict(reference) == expected, "fusion_analysis_reference_mismatch")


def validate_fusion_record(
    document: Mapping[str, Any],
    analyses_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    required = {
        "schema",
        "fusion_version",
        "pool",
        "mint",
        "event_id",
        "cutoff_ns",
        "temporal_rule",
        "supported_producers",
        "present_agents",
        "missing_agents",
        "agents",
        "shadow_only",
        "decision_effect",
    }
    allowed = required | {"fusion_id"}
    _require(set(document) == required or set(document) == allowed, "invalid_fusion_record_fields")
    _require(document["schema"] == SCHEMA and document["fusion_version"] == VERSION, "unsupported_fusion_schema")
    _require(document["temporal_rule"] == TEMPORAL_RULE, "unsupported_fusion_temporal_rule")
    _require(document["supported_producers"] == list(SUPPORTED_PRODUCERS), "fusion_producers_changed")
    _require(document["shadow_only"] is True and document["decision_effect"] == "NONE", "fusion_shadow_only_required")
    for key in ("pool", "mint", "event_id"):
        _require(isinstance(document[key], str) and document[key], "invalid_fusion_identity")
    cutoff = document["cutoff_ns"]
    _require(type(cutoff) is int and cutoff >= 0, "invalid_fusion_cutoff")
    agents = document["agents"]
    _require(isinstance(agents, dict) and tuple(sorted(agents)) == tuple(sorted(SUPPORTED_PRODUCERS)), "invalid_fusion_agents")
    present = []
    missing = []
    for name in SUPPORTED_PRODUCERS:
        reference = agents[name]
        _require(isinstance(reference, dict), "invalid_fusion_agent_reference")
        if reference.get("status") == "PRESENT":
            present.append(name)
            _require(set(reference) == PRESENT_REFERENCE_FIELDS, "invalid_fusion_agent_reference_fields")
            _require(reference.get("cutoff_ns") == cutoff, "fusion_cutoff_mismatch")
            analysis_id = reference.get("analysis_id")
            _require(_is_sha256(analysis_id), "invalid_fusion_analysis_id")
            _require(
                isinstance(reference.get("agent_version"), str) and bool(reference["agent_version"]),
                "invalid_fusion_agent_version",
            )
            _require(
                isinstance(reference.get("input_hashes"), list)
                and bool(reference["input_hashes"])
                and all(_is_sha256(value) for value in reference["input_hashes"]),
                "invalid_fusion_input_hashes",
            )
            _require(isinstance(reference.get("provenance"), list), "invalid_fusion_provenance")
            _require(
                isinstance(reference.get("coverage"), str) and bool(reference["coverage"]),
                "invalid_fusion_coverage",
            )
            _require(
                isinstance(reference.get("missing"), list)
                and all(isinstance(value, str) and value for value in reference["missing"]),
                "invalid_fusion_missing_dimensions",
            )
            _require(reference.get("classification") in ("OBSERVED", "DERIVED", "UNKNOWN"), "invalid_fusion_classification")
            _require(reference.get("shadow_only") is True, "fusion_source_not_shadow")
            assert_cutoff(reference.get("provenance"), cutoff)
            if analyses_by_id is not None:
                _require(analysis_id in analyses_by_id, "fusion_analysis_not_in_store")
                envelope = validate_envelope(analyses_by_id[analysis_id])
                _require(envelope["agent"] == name, "fusion_agent_reference_mismatch")
                _require(
                    (envelope["pool"], envelope["mint"], envelope["event_id"], envelope["cutoff_ns"])
                    == (document["pool"], document["mint"], document["event_id"], cutoff),
                    "fusion_context_mismatch",
                )
                _assert_reference_matches(reference, envelope)
        elif reference.get("status") == "MISSING":
            missing.append(name)
            _require(reference == _missing_reference(), "invalid_missing_agent_reference")
        else:
            raise ValueError("invalid_fusion_agent_status")
    _require(bool(present), "fusion_requires_present_analysis")
    _require(document["present_agents"] == present and document["missing_agents"] == missing, "fusion_agent_index_mismatch")
    assert_no_decisions(document)
    assert_unknown_is_not_zero(document)
    expected_id = sha256_json({key: document[key] for key in required})
    if "fusion_id" in document:
        _require(document["fusion_id"] == expected_id, "fusion_hash_mismatch")
    return dict(document)
