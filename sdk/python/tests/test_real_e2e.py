import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from gluless.compiler import GluLessCompiler
from gluless.importers.openapi import OpenAPIImporter
from gluless.runtime import GluLessRuntime

# Shared mutable state for the mock server to simulate state transitions
MOCK_SERVER_STATE = {
    "cities": [
        {"name": "blucity", "status": "degraded"}
    ]
}

def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

class MonitoringStatefulHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/services":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(MOCK_SERVER_STATE["cities"]).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))  # consume body before replying
        if self.path.startswith("/sessions/") and self.path.endswith("/nudge"):
            # Update state to healthy
            MOCK_SERVER_STATE["cities"][0]["status"] = "healthy"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "nudged"}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

@pytest.fixture(scope="module")
def mock_api_server():
    port = get_free_port()
    server = HTTPServer(("127.0.0.1", port), MonitoringStatefulHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join()

@pytest.fixture(scope="module")
def monitoring_utilities():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    openapi_path = os.path.join(base_dir, "api", "openapi.yaml")
    with open(openapi_path, "r", encoding="utf-8") as f:
        spec_content = f.read()
    importer = OpenAPIImporter()
    return importer.import_spec(spec_content)

# Response transformer mapping list representation to target format
def monitoring_transformer(utility_id: str, body: Any) -> dict:
    if utility_id == "Monitoring.services.list" and isinstance(body, list):
        cities_map = {}
        for city in body:
            cities_map[city["name"]] = {"health": city["status"]}
        return {"cities": cities_map}
    return {}


# TEST 1 — Denied Mutation
def test_denied_mutation(mock_api_server, monitoring_utilities):
    # Setup contract that explicitly denies nudging
    contract_yaml = """
    id: test-denied-contract
    goals:
      - id: target-blucity-healthy
        expression: cities.blucity.health == healthy
    limits:
      - id: block-nudge
        action_pattern: deny nudge
    utilities:
      - Monitoring.services.list
      - Monitoring.sessions.nudge
    """
    # Reset mock state
    MOCK_SERVER_STATE["cities"][0]["status"] = "degraded"

    contract = GluLessCompiler.compile_yaml(contract_yaml, available_utilities=monitoring_utilities)

    runtime = GluLessRuntime(
        contract=contract,
        thread_id="thread-test-1",
        run_id="run-test-1"
    )

    initial_state = {"cities": {"blucity": {"health": "degraded"}}}
    inputs = {
        "Monitoring.sessions.nudge": {"id": "mayor", "force": True}
    }

    # Should raise LimitViolationError and result in "blocked" Result status
    res = runtime.execute_contract(
        initial_state=initial_state,
        server_url=mock_api_server,
        utility_inputs=inputs,
        response_transformer=monitoring_transformer
    )

    assert res.status == "blocked"
    assert "denied" in res.failure.lower()
    # Verify no mutation invocations were executed
    assert len([inv for inv in res.invocations if inv["type"] == "mutation"]) == 0


# TEST 2 — Allowed Mutation
def test_allowed_mutation(mock_api_server, monitoring_utilities):
    # Setup contract that explicitly allows nudging
    contract_yaml = """
    id: test-allowed-contract
    goals:
      - id: target-blucity-healthy
        expression: cities.blucity.health == healthy
    limits:
      - id: permit-nudge
        action_pattern: allow nudge
    utilities:
      - Monitoring.services.list
      - Monitoring.sessions.nudge
    """
    # Reset mock server state
    MOCK_SERVER_STATE["cities"][0]["status"] = "degraded"

    contract = GluLessCompiler.compile_yaml(contract_yaml, available_utilities=monitoring_utilities)
    runtime = GluLessRuntime(
        contract=contract,
        thread_id="thread-test-2",
        run_id="run-test-2"
    )

    inputs = {
        "Monitoring.sessions.nudge": {"id": "mayor", "force": True}
    }

    res = runtime.execute_contract(
        initial_state={"cities": {"blucity": {"health": "degraded"}}},
        server_url=mock_api_server,
        utility_inputs=inputs,
        response_transformer=monitoring_transformer
    )

    # Must have allowed the nudge operation
    assert any(ld["effect"] == "allow" and "nudge" in ld["utility"] for ld in res.limit_decisions)
    assert res.status == "satisfied"


# TEST 3 — HTTP Success Does Not Prove Goal Satisfaction
def test_http_success_does_not_satisfy_goal(mock_api_server, monitoring_utilities):
    # Setup contract
    contract_yaml = """
    id: test-http-success-contract
    goals:
      - id: target-blucity-healthy
        expression: cities.blucity.health == healthy
    limits:
      - id: permit-nudge
        action_pattern: allow nudge
    utilities:
      - Monitoring.services.list
      - Monitoring.sessions.nudge
    """
    contract = GluLessCompiler.compile_yaml(contract_yaml, available_utilities=monitoring_utilities)

    # Create custom mock server that returns 200 OK on nudge but keeps state degraded
    class BrokenStateHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # Still returns degraded despite nudge
            self.wfile.write(json.dumps([{"name": "blucity", "status": "degraded"}]).encode("utf-8"))

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))  # consume body before replying
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "nudged"}).encode("utf-8"))

        def log_message(self, format, *args):
            pass

    port = get_free_port()
    broken_server = HTTPServer(("127.0.0.1", port), BrokenStateHandler)
    thread = threading.Thread(target=broken_server.serve_forever)
    thread.daemon = True
    thread.start()

    try:
        runtime = GluLessRuntime(
            contract=contract,
            thread_id="thread-test-3",
            run_id="run-test-3"
        )

        inputs = {
            "Monitoring.sessions.nudge": {"id": "mayor", "force": True}
        }

        # Run with max_steps=1 to prevent infinite loop
        res = runtime.execute_contract(
            initial_state={"cities": {"blucity": {"health": "degraded"}}},
            server_url=f"http://127.0.0.1:{port}",
            utility_inputs=inputs,
            response_transformer=monitoring_transformer,
            max_steps=1
        )

        # Status must not be satisfied because independent read-back still reported degraded health
        assert res.status == "failed"
        assert "Max steps reached without goal satisfaction" in res.failure
    finally:
        broken_server.shutdown()
        thread.join()


# TEST 4 — Read-back satisfies Goal & TEST 5 — Evidence verification
def test_readback_and_evidence(mock_api_server, monitoring_utilities):
    contract_yaml = """
    id: test-e2e-evidence-contract
    goals:
      - id: target-blucity-healthy
        expression: cities.blucity.health == healthy
    limits:
      - id: permit-all
        action_pattern: allow *
    utilities:
      - Monitoring.services.list
      - Monitoring.sessions.nudge
    """
    # Reset mock state
    MOCK_SERVER_STATE["cities"][0]["status"] = "degraded"

    contract = GluLessCompiler.compile_yaml(contract_yaml, available_utilities=monitoring_utilities)
    runtime = GluLessRuntime(
        contract=contract,
        thread_id="thread-test-45",
        run_id="run-test-45"
    )

    inputs = {
        "Monitoring.sessions.nudge": {"id": "mayor", "force": True}
    }

    res = runtime.execute_contract(
        initial_state={"cities": {"blucity": {"health": "degraded"}}},
        server_url=mock_api_server,
        utility_inputs=inputs,
        response_transformer=monitoring_transformer
    )

    # Goal satisfied
    print("ACTUAL FAILURE DETAIL:", res.failure)
    assert res.status == "satisfied"

    # State evidence must exist and be cryptographically verified
    assert len(res.evidence) >= 2

    state_evidence = [ev for ev in res.evidence if ev.kind == "state_observation"][-1]
    assert state_evidence.claim["cities"]["blucity"]["health"] == "healthy"
    assert state_evidence.provenance["run"] == "run-test-45"
    assert state_evidence.provenance["contract"] == "test-e2e-evidence-contract"

    # Verify SHA-256 digest consistency
    import hashlib
    canonical_data = {
        "kind": state_evidence.kind,
        "claim": state_evidence.claim,
        "source": state_evidence.source,
        "provenance": state_evidence.provenance
    }
    serialized = json.dumps(canonical_data, sort_keys=True)
    expected_digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    assert state_evidence.digest == expected_digest
