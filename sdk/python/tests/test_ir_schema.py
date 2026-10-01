"""The IR has exactly one definition, and it round-trips.

`gluless.models` is authored; `api/contract.schema.json` is generated from it.
These tests are the drift gate: if the two ever disagree, or if a real OpenAPI
document stops surviving serialise/deserialise unchanged, this file fails.
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from pydantic import ValidationError

from gluless import schema as ir_schema
from gluless.importers.openapi import OpenAPIImporter
from gluless.models import (
    IR_VERSION,
    Contract,
    EvidenceRequirement,
    Goal,
    Limit,
    SideEffectType,
    Utility,
    UtilityTransport,
    UtilityType,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_SPEC = REPO_ROOT / "api" / "openapi.yaml"


# --------------------------------------------------------------- single source


def test_checked_in_schema_matches_the_models():
    """The generated artifact must be current. If this fails the fix is
    `python -m gluless.schema --write`, never a hand edit of the JSON."""
    target = ir_schema.schema_path()
    assert target.exists(), f"{target} is missing; run: python -m gluless.schema --write"
    assert target.read_text(encoding="utf-8") == ir_schema.render(), (
        f"{target} is stale; run: python -m gluless.schema --write"
    )


def test_generated_schema_is_a_valid_json_schema():
    doc = ir_schema.build_schema()
    jsonschema.Draft202012Validator.check_schema(doc)
    assert doc["$id"].endswith(".json")
    assert doc["title"] == "Contract"


def test_schema_declares_the_authority_bearing_fields():
    """A Limit selector targets `utility.id` and reads `side_effects`/`type`.
    Those must be required by the schema, not optional conveniences."""
    doc = ir_schema.build_schema()
    utility = doc["$defs"]["Utility"]
    for name in ("id", "name", "namespace", "type", "side_effects", "transport"):
        assert name in utility["required"], name
    assert doc["required"] == ["id", "goals", "limits", "utilities"]


def test_schema_forbids_undeclared_keys():
    doc = ir_schema.build_schema()
    for name, definition in doc["$defs"].items():
        if definition.get("type") == "object":
            assert definition.get("additionalProperties") is False, name
    assert doc["additionalProperties"] is False


# ------------------------------------------------------------------ validation


def test_unknown_key_is_rejected_by_the_models_and_by_the_schema():
    bad = {
        "id": "c",
        "goals": [],
        "limits": [],
        "utilities": [],
        "totally_unknown": True,
    }
    with pytest.raises(ValidationError):
        Contract.model_validate(bad)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, ir_schema.build_schema())


def test_invalid_side_effect_class_is_rejected():
    with pytest.raises(ValidationError):
        Utility.model_validate(
            {
                "id": "N.r.a",
                "name": "r.a",
                "namespace": "N",
                "description": "",
                "type": "read",
                "side_effects": "not-a-real-effect",
                "transport": {"type": "openapi", "method": "GET", "path": "/r"},
            }
        )


# ------------------------------------------------------------------ round-trip


def _import_contract() -> Contract:
    utilities = OpenAPIImporter().import_spec(
        REAL_SPEC.read_text(encoding="utf-8"), source_uri=str(REAL_SPEC)
    )
    assert utilities, "fixture spec produced no utilities"
    return Contract(
        id="roundtrip",
        goals=[Goal(id="g1", expression="services.status == healthy")],
        limits=[Limit(id="l1", action_pattern="deny *"), Limit(id="l2", action_pattern="allow read")],
        utilities=utilities,
        evidence_requirements=[EvidenceRequirement(id="e1", assertion="response.status == 200")],
    )


def test_real_openapi_spec_round_trips_through_json_unchanged():
    """Acceptance test: a real OpenAPI document imports to IR, serialises,
    deserialises, and produces an identical IR."""
    original = _import_contract()

    document = json.loads(json.dumps(original.model_dump(mode="json")))
    restored = Contract.model_validate(document)

    assert restored == original
    assert restored.model_dump(mode="json") == document


def test_round_tripped_document_validates_against_the_checked_in_schema():
    """Proves the generated artifact is usable by a consumer that has no
    Pydantic -- the Go and TypeScript SDKs read this file, not models.py."""
    document = _import_contract().model_dump(mode="json")
    stored = json.loads(ir_schema.schema_path().read_text(encoding="utf-8"))
    jsonschema.validate(document, stored)


def test_round_trip_preserves_provenance_and_declared_effects():
    original = _import_contract()
    restored = Contract.model_validate(original.model_dump(mode="json"))
    assert len(restored.utilities) == len(original.utilities)
    for before, after in zip(original.utilities, restored.utilities, strict=True):
        assert after.provenance == before.provenance
        assert after.side_effects is before.side_effects
        assert after.type is before.type
        assert after.transport == before.transport
        assert after.description == before.description


def test_contract_declares_its_ir_version():
    assert _import_contract().model_dump(mode="json")["ir_version"] == IR_VERSION


def test_enum_members_survive_a_string_round_trip():
    utility = Utility(
        id="N.r.a",
        name="r.a",
        namespace="N",
        description="d",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.PRIVILEGE_CHANGE,
        transport=UtilityTransport(type="openapi", method="POST", path="/r"),
    )
    dumped = utility.model_dump(mode="json")
    assert dumped["type"] == "mutation"
    assert dumped["side_effects"] == "privilege_change"
    assert Utility.model_validate(dumped) == utility


# ------------------------------------------- the registry is the same IR, cached


def test_registry_round_trip_is_lossless(tmp_path):
    """`register()` then `resolve()` used to drop `description` and lower-case
    `namespace`/`name`, because the registry re-declared the IR by hand. It now
    stores and reads back the canonical serialization."""
    from gluless.registry import UtilityRegistry

    utility = Utility(
        id="GasCity.sessions.nudge",
        name="sessions.nudge",
        namespace="GasCity",
        description="Nudge a session",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=UtilityTransport(type="openapi", method="POST", path="/sessions/{id}/nudge"),
        provenance={"source_type": "openapi", "operation_id": "nudgeSession"},
    )
    registry = UtilityRegistry(registry_path=str(tmp_path / "registry.json"))
    registry_id = registry.register(utility, "file:///spec.yaml", "digest")

    reloaded = UtilityRegistry(registry_path=str(tmp_path / "registry.json"))
    assert reloaded.resolve(registry_id) == utility


def test_yaml_fixture_spec_is_parseable():
    """Guards the acceptance fixture itself: if api/openapi.yaml stops being a
    real OpenAPI document the round-trip test above proves nothing."""
    document = yaml.safe_load(REAL_SPEC.read_text(encoding="utf-8"))
    assert document["openapi"].startswith("3.")
    assert len(document["paths"]) >= 3
