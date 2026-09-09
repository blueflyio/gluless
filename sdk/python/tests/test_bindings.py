import json

from gluless.bindings import ExecutableBinding, UtilityResolver
from gluless.models import SideEffectType, Utility, UtilityTransport, UtilityType


def _binding(**kw) -> ExecutableBinding:
    base = dict(server="http://api.test/v0", method="POST", path="/sessions/{id}/nudge",
                parameters=[{"name": "id", "in": "path"}, {"name": "dry", "in": "query"}],
                request_body={"type": "object", "properties": {"force": {"type": "boolean"}}},
                headers={"X-API-Token": "secret-value"})
    base.update(kw)
    return ExecutableBinding(**base)


def test_path_params_are_percent_encoded():
    req = _binding().build_request({"id": "../admin", "force": True})
    assert req.full_url == "http://api.test/v0/sessions/..%2Fadmin/nudge"


def test_only_declared_body_properties_are_sent():
    req = _binding().build_request({"id": "s1", "dry": "1", "force": True, "junk": "x"})
    assert req.full_url == "http://api.test/v0/sessions/s1/nudge?dry=1"
    assert json.loads(req.data) == {"force": True}


def test_missing_path_param_is_a_typed_error_not_a_request():
    res = _binding().execute({"force": True})
    assert res["status_code"] == 0 and "Missing path parameter" in res["error"]


def test_headers_are_sent_but_never_recorded():
    req = _binding().build_request({"id": "s1"})
    assert req.get_header("X-api-token") == "secret-value"
    res = _binding(server="http://127.0.0.1:9").execute({"id": "s1"})
    assert "secret-value" not in json.dumps(res)


def test_resolver_falls_back_to_declared_server():
    u = Utility(id="Ns.a.list", name="a.list", namespace="Ns", description="", type=UtilityType.READ,
                side_effects=SideEffectType.READ,
                transport=UtilityTransport(type="openapi", method="GET", path="/a", servers=["http://declared/v1"]))
    assert UtilityResolver().resolve(u).server == "http://declared/v1"
    assert UtilityResolver("http://override/").resolve(u).server == "http://override"
