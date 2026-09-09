"""Identity, side-effect and fail-closed behaviour of the OpenAPI importer."""
import os

import pytest

from gluless.importers.openapi import OpenAPIImporter, UtilityImportError, derive_utility_name
from gluless.models import SideEffectType, UtilityType

REPO_SPEC = os.path.join(os.path.dirname(__file__), "..", "..", "..", "api", "openapi.yaml")


def _spec(paths: str, extra: str = "") -> str:
    return f"openapi: 3.1.0\ninfo: {{title: Nested API, version: '2.0'}}\n{extra}paths:\n{paths}"


def test_nested_resources_keep_full_path():
    assert derive_utility_name("GET", "/v0/city/{c}/sessions") == ("city.sessions", "list")
    assert derive_utility_name("GET", "/v0/city/{c}/session/{id}") == ("city.session", "read")
    assert derive_utility_name("POST", "/v0/city/{c}/session/{id}/kill") == ("city.session", "kill")
    assert derive_utility_name("POST", "/v0/city/{c}/sessions", sibling_methods=("get",)) == ("city.sessions", "create")
    assert derive_utility_name("POST", "/v0/city/{c}/sling") == ("city", "sling")
    assert derive_utility_name("PATCH", "/v0/city/{c}/agent/{a}") == ("city.agent", "update")
    assert derive_utility_name("DELETE", "/v0/city/{c}/bead/{id}") == ("city.bead", "delete")


def test_path_with_only_parameters_is_an_error():
    with pytest.raises(UtilityImportError):
        derive_utility_name("POST", "/{id}")


def test_no_collisions_on_a_nested_api():
    spec = _spec(
        "  /users: {get: {responses: {'200': {description: ok}}}}\n"
        "  /users/{id}/posts: {get: {responses: {'200': {description: ok}}}}\n"
        "  /users/{id}: {delete: {responses: {'204': {description: gone}}}, post: {responses: {'200': {description: ok}}}}\n"
        "  /users/{id}/deactivate: {post: {responses: {'200': {description: ok}}}}\n"
    )
    us = OpenAPIImporter().import_spec(spec)
    ids = sorted(u.id for u in us)
    assert ids == sorted([
        "NestedAPI.users.list",
        "NestedAPI.users.posts.list",
        "NestedAPI.users.delete",
        "NestedAPI.users.create",
        "NestedAPI.users.deactivate",
    ])


def test_duplicate_identity_fails_closed():
    spec = _spec(
        "  /a: {post: {x-gluless-name: X.a.do, responses: {'200': {description: ok}}}}\n"
        "  /b: {post: {x-gluless-name: X.a.do, responses: {'200': {description: ok}}}}\n"
    )
    with pytest.raises(UtilityImportError, match="Duplicate utility id"):
        OpenAPIImporter().import_spec(spec)


def test_rpc_post_is_unknown_not_create():
    spec = _spec("  /session/{id}/kill: {post: {responses: {'200': {description: ok}}}}\n")
    (u,) = OpenAPIImporter().import_spec(spec)
    assert u.side_effects == SideEffectType.UNKNOWN
    assert u.type == UtilityType.MUTATION


def test_exclude_extension_is_honoured():
    spec = _spec(
        "  /health: {get: {x-gluless-exclude: true, responses: {'200': {description: ok}}}}\n"
        "  /things: {get: {responses: {'200': {description: ok}}}}\n"
    )
    ids = [u.id for u in OpenAPIImporter().import_spec(spec)]
    assert ids == ["NestedAPI.things.list"]


def test_status_codes_normalised_and_no_content_is_none():
    spec = _spec("  /things/{id}: {delete: {responses: {204: {description: gone}}}}\n")
    (u,) = OpenAPIImporter().import_spec(spec)
    assert u.transport.responses == {"204": None}


def test_operation_params_override_path_params():
    spec = _spec(
        "  /things/{id}:\n"
        "    parameters: [{name: id, in: path, required: true, schema: {type: integer}}]\n"
        "    get:\n"
        "      parameters: [{name: id, in: path, required: true, schema: {type: string}}, {name: q, in: query, schema: {type: string}}]\n"
        "      responses: {'200': {description: ok}}\n"
    )
    (u,) = OpenAPIImporter().import_spec(spec)
    by_name = {p["name"]: p for p in u.transport.parameters}
    assert len(u.transport.parameters) == 2
    assert by_name["id"]["schema"]["type"] == "string"


def test_servers_security_and_provenance_are_carried():
    spec = _spec(
        "  /things: {get: {operationId: listThings, deprecated: true, responses: {'200': {description: ok}}}}\n"
        "  /open: {get: {security: [], responses: {'200': {description: ok}}}}\n",
        extra="servers: [{url: 'http://localhost:9/v2'}]\nsecurity: [{ApiKey: []}]\n",
    )
    us = {u.id: u for u in OpenAPIImporter().import_spec(spec, source_uri="file://spec.yaml")}
    t = us["NestedAPI.things.list"]
    assert t.transport.servers == ["http://localhost:9/v2"]
    assert t.transport.deprecated is True
    assert t.auth == [{"ApiKey": []}]
    assert t.version == "2.0"
    assert t.provenance["operation_id"] == "listThings"
    assert t.provenance["source_uri"] == "file://spec.yaml"
    assert len(t.provenance["source_digest"]) == 64
    assert us["NestedAPI.open.list"].auth == []  # explicit opt-out survives


def test_repo_example_spec_imports_cleanly():
    with open(REPO_SPEC, encoding="utf-8") as f:
        us = OpenAPIImporter().import_spec(f.read(), source_uri="api/openapi.yaml")
    ids = {u.id for u in us}
    assert ids == {"Monitoring.services.list", "Monitoring.service.create", "Monitoring.sessions.nudge"}
    nudge = next(u for u in us if u.id == "Monitoring.sessions.nudge")
    assert nudge.side_effects == SideEffectType.EXTERNAL_MESSAGE
    assert nudge.auth == [{"ApiKeyAuth": []}]
    assert nudge.transport.servers == ["http://localhost:8000/v0"]
