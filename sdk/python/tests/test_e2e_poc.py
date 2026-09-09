import json
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from ag_ui.core import BaseEvent, EventType

from gluless.compiler import GluLessCompiler
from gluless.importers.openapi import OpenAPIImporter
from gluless.runtime import GluLessRuntime


# Helper to find a free TCP port
def get_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port

# Mock HTTP server for the example Monitoring API (api/openapi.yaml)
class GasCityMockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v0/services":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response_data = [
                {"name": "blucity", "status": "healthy"},
                {"name": "gascity", "status": "degraded"}
            ]
            self.wfile.write(json.dumps(response_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    # Suppress server logging to keep test output clean
    def log_message(self, format, *args):
        pass

@pytest.fixture(scope="module")
def mock_gascity_server():
    port = get_free_port()
    server = HTTPServer(("127.0.0.1", port), GasCityMockHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread.join()

def test_e2e_compiler_and_runtime_poc(mock_gascity_server):
    # 1. Read openapi.yaml spec and import capabilities
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    openapi_path = os.path.join(base_dir, "api", "openapi.yaml")

    with open(openapi_path, "r", encoding="utf-8") as f:
        spec_content = f.read()

    importer = OpenAPIImporter()
    available_utils = importer.import_spec(spec_content)

    # Verify we resolved the Monitoring utilities
    util_map = {u.id: u for u in available_utils}
    assert "Monitoring.services.list" in util_map

    # 2. Write and compile the contract
    contract_yaml = """
    id: monitoring-contract
    goals:
      - id: target-blucity-healthy
        expression: cities.blucity.health == healthy
        description: Ensure blucity is healthy in the network
    limits:
      - id: deny-financial-actions
        action_pattern: deny financial
    utilities:
      - Monitoring.services.list
    """

    contract = GluLessCompiler.compile_yaml(contract_yaml, available_utilities=available_utils)
    assert contract.id == "monitoring-contract"

    # 3. Define HTTP Executor utilizing the compiled utility transports
    # In a real environment, the runtime maps the transport schema to an HTTP call
    def execute_http_call(state: dict) -> dict:
        url = f"{mock_gascity_server}/v0/services"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    # Map the array response to state representation: {"cities": {"blucity": {"health": "healthy"}}}
                    cities_state = {}
                    for city in data:
                        cities_state[city["name"]] = {"health": city["status"]}
                    return {"cities": cities_state}
        except Exception as e:
            return {"error": str(e)}
        return {}

    executors = {
        "Monitoring.services.list": execute_http_call
    }

    # 4. Execute Contract under next-valid-action loop
    emitted_events: list[BaseEvent] = []
    def log_event(ev: BaseEvent):
        emitted_events.append(ev)

    runtime = GluLessRuntime(
        contract=contract,
        on_event=log_event,
        thread_id="e2e-thread-id",
        run_id="e2e-run-id"
    )

    # Initial state lacks blucity health
    initial_state = {"cities": {"blucity": {"health": "unknown"}}}

    result = runtime.execute_contract(initial_state, executors)

    # Verify target achieved and correct state set
    assert result["status"] == "success"
    assert result["final_state"]["cities"]["blucity"]["health"] == "healthy"

    # 5. Verify full AG-UI Event Trace
    event_types = [e.type for e in emitted_events]

    assert EventType.RUN_STARTED in event_types
    assert EventType.STEP_STARTED in event_types
    assert EventType.STATE_SNAPSHOT in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TOOL_CALL_RESULT in event_types
    assert EventType.RUN_FINISHED in event_types

    # Ensure RunStartedEvent matches run IDs
    start_event = next(e for e in emitted_events if e.type == EventType.RUN_STARTED)
    assert start_event.thread_id == "e2e-thread-id"
    assert start_event.run_id == "e2e-run-id"
