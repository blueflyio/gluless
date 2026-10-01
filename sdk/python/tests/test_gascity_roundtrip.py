"""Real upstream round-trip: Gas City Supervisor API -> Utilities -> IR -> JSON Schema -> IR.

Fixture: tests/fixtures/gascity-openapi.subset.json, a pruned copy of the
upstream document pinned by commit (see make_gascity_subset.py). The subset
keeps every path that collides under derived identity, so this is the
collision policy's regression test, not a smoke test.
"""
import json
from pathlib import Path

import jsonschema
import pytest

from gluless import ir
from gluless import schema as ir_schema
from gluless.importers.openapi import OpenAPIImporter, UtilityImportError
from gluless.models import Contract, Goal, Limit, SideEffectType

FIXTURE = Path(__file__).with_name("fixtures") / "gascity-openapi.subset.json"

# Sidecar: the upstream document is not ours to annotate with x-gluless-name.
# The spec tie-break already keeps these unique (`...read.base`); the sidecar
# replaces a parameter-name-derived identity with a declared semantic one.
GASCITY_OVERRIDES = {
    "GET /v0/city/{cityName}/agent/{dir}/{base}": "GasCitySupervisorAPI.city.agent.qualified.read",
    "PATCH /v0/city/{cityName}/agent/{dir}/{base}": "GasCitySupervisorAPI.city.agent.qualified.update",
    "DELETE /v0/city/{cityName}/agent/{dir}/{base}": "GasCitySupervisorAPI.city.agent.qualified.delete",
    "GET /v0/city/{cityName}/agent/{dir}/{base}/output": "GasCitySupervisorAPI.city.agent.qualified.output.read",
    "GET /v0/city/{cityName}/agent/{dir}/{base}/output/stream": "GasCitySupervisorAPI.city.agent.qualified.output.stream",
    "POST /v0/city/{cityName}/agent/{dir}/{base}/{action}": "GasCitySupervisorAPI.city.agent.qualified.action",
    "GET /v0/city/{cityName}/patches/agent/{dir}/{base}": "GasCitySupervisorAPI.city.patches.agent.qualified.read",
    "DELETE /v0/city/{cityName}/patches/agent/{dir}/{base}": "GasCitySupervisorAPI.city.patches.agent.qualified.delete",
}


@pytest.fixture(scope="module")
def spec_text() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_fixture_is_pinned_to_upstream(spec_text):
    meta = json.loads(spec_text)["x-gluless-fixture"]
    assert meta["upstream_commit"] == "02e058598391329b7927405351ff62af89c44feb"
    assert len(meta["upstream_sha256"]) == 64


def test_spec_tie_break_makes_derived_identity_unique(spec_text):
    """docs/gluless-specification.md: a parameter segment not preceded by a
    literal contributes its name to the action. That is the only tie-break the
    importer applies; everything else that collides is an import error."""
    utilities = OpenAPIImporter().import_spec(spec_text)
    ids = [u.id for u in utilities]
    assert len(ids) == len(set(ids))
    assert "GasCitySupervisorAPI.city.agent.read" in ids
    assert "GasCitySupervisorAPI.city.agent.read.base" in ids
    assert all(u.provenance["identity_source"] == "derived" for u in utilities)


def test_true_collisions_still_fail_closed():
    spec = json.dumps({
        "openapi": "3.1.0", "info": {"title": "X", "version": "1"},
        "paths": {
            "/a": {"post": {"x-gluless-name": "X.a.do", "responses": {"200": {"description": "ok"}}}},
            "/b": {"post": {"x-gluless-name": "X.a.do", "responses": {"200": {"description": "ok"}}}},
        },
    })
    with pytest.raises(UtilityImportError, match="Duplicate utility id"):
        OpenAPIImporter().import_spec(spec)


def test_overrides_resolve_every_collision(spec_text):
    utilities = OpenAPIImporter(name_overrides=GASCITY_OVERRIDES).import_spec(
        spec_text, source_uri="gastownhall/gascity@02e0585 openapi.json"
    )
    ids = [u.id for u in utilities]
    assert len(ids) == len(set(ids))
    by_id = {u.id: u for u in utilities}
    # derived identities keep the hierarchy
    assert "GasCitySupervisorAPI.cities.list" in by_id
    assert "GasCitySupervisorAPI.city.sessions.create" in by_id
    assert by_id["GasCitySupervisorAPI.city.session.kill"].side_effects == SideEffectType.UNKNOWN
    # overridden identities record their source
    q = by_id["GasCitySupervisorAPI.city.agent.qualified.read"]
    assert q.provenance["identity_source"] == "override"
    assert q.provenance["location"] == "GET /v0/city/{cityName}/agent/{dir}/{base}"
    assert by_id["GasCitySupervisorAPI.city.agent.read"].provenance["identity_source"] == "derived"


def test_ir_roundtrip_through_json_schema(spec_text):
    utilities = OpenAPIImporter(name_overrides=GASCITY_OVERRIDES).import_spec(spec_text)
    contract = Contract(
        id="gascity-city-healthy",
        goals=[Goal(id="g1", expression="city.status == running")],
        limits=[
            Limit(id="l0", action_pattern="deny *"),
            Limit(id="l1", action_pattern="allow GasCitySupervisorAPI.cities.list"),
            Limit(id="l2", action_pattern="require approval for GasCitySupervisorAPI.city.session.kill"),
        ],
        utilities=utilities,
    )
    text = ir.dump_contract(contract)
    doc = json.loads(text)
    jsonschema.Draft202012Validator(ir_schema.build_schema()).validate(doc)
    reloaded = ir.load_contract(text)
    assert reloaded == contract
    assert ir.digest(reloaded) == ir.digest(contract)


def test_digest_is_canonical_and_content_bound():
    a = Contract(id="c", goals=[Goal(id="g", expression="x == 1")], limits=[], utilities=[])
    b = Contract.model_validate({"utilities": [], "limits": [], "goals": [{"expression": "x == 1", "id": "g"}], "id": "c"})
    assert ir.digest(a) == ir.digest(b)  # key order never matters
    assert ir.digest(a).startswith("sha256:")
    c = a.model_copy(update={"limits": [Limit(id="l", action_pattern="allow *")]})
    assert ir.digest(c) != ir.digest(a)  # authority change changes identity
    assert ir.contract_id_ref(a) == f"c@{ir.digest(a)}"
