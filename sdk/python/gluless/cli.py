"""GluLess CLI — prove a Goal under Limits via typed Utilities.

Contract path, OpenAPI path, and base URL come from argv or environment
variables only. Callers must not interpolate bead titles or formula vars into
`sh -c`.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from gluless.bindings import UtilityResolver
from gluless.evidence import EvidenceBuilder
from gluless.importers.openapi import OpenAPIImporter
from gluless.limits import EFFECT_ALLOW, EFFECT_APPROVAL, LimitEvaluator
from gluless.models import Contract, Goal, Utility, UtilityType
from gluless.parser import parse_file
from gluless.runtime import GluLessRuntime

ENV_CONTRACT = "GLULESS_CONTRACT"
ENV_OPENAPI = "GLULESS_OPENAPI"
ENV_BASE_URL = "GLULESS_BASE_URL"


class _AllHealthyHandler(BaseHTTPRequestHandler):
    """Minimal Monitoring mock: GET /v0/services returns all-healthy services."""

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/v0/services", "/services"):
            body = json.dumps(
                [
                    {"name": "auth-service", "status": "healthy", "version": "v1.2.0", "instances": 3},
                    {"name": "api-gateway", "status": "healthy", "version": "v2.0.4", "instances": 2},
                ]
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _start_mock() -> Tuple[str, HTTPServer, threading.Thread]:
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), _AllHealthyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}/v0", server, thread


def _bind_utilities(contract: Contract, openapi_path: Path) -> Contract:
    spec = openapi_path.read_text(encoding="utf-8")
    available = {u.id: u for u in OpenAPIImporter().import_spec(spec)}
    bound: List[Utility] = []
    missing: List[str] = []
    for stub in contract.utilities:
        resolved = available.get(stub.id)
        if resolved is None:
            missing.append(stub.id)
        else:
            bound.append(resolved)
    if missing:
        raise SystemExit(f"PARSE=FAIL utilities not in OpenAPI: {', '.join(missing)}")
    return Contract(
        id=contract.id,
        goals=list(contract.goals),
        limits=list(contract.limits),
        utilities=bound,
        evidence_requirements=list(contract.evidence_requirements),
    )


def _services_world_state(body: Any) -> Dict[str, Any]:
    if not isinstance(body, list):
        return {"services": {"healthy": False, "listed": False, "items": body, "count": 0}}
    healthy = all(isinstance(item, dict) and item.get("status") == "healthy" for item in body)
    return {
        "services": {
            "healthy": healthy,
            "listed": len(body) > 0,
            "items": body,
            "count": len(body),
        }
    }


def _evidence_pass(assertion: str, http_status: int, body: Any, world_state: Dict[str, Any]) -> bool:
    lower = assertion.strip().lower()
    if "response.status == 200" in lower:
        return http_status == 200
    if "response.schema valid" in lower:
        return isinstance(body, list) and len(body) > 0 and all(isinstance(i, dict) for i in body)
    if "services observed" in lower or "items observed" in lower:
        return isinstance(body, list) and len(body) > 0
    if "==" in assertion:
        return GluLessRuntime.evaluate_goal(world_state, Goal(id="_ev", expression=assertion))
    return http_status == 200 and bool(body)


def prove(contract_path: Path, openapi_path: Path, base_url: Optional[str], use_mock: bool) -> int:
    status = {
        "PARSE": "FAIL",
        "AUTHORIZE": "FAIL",
        "HTTP_EXECUTION": "FAIL",
        "GOAL_EVALUATION": "FAIL",
    }

    contract = _bind_utilities(parse_file(str(contract_path)), openapi_path)
    status["PARSE"] = "PASS"
    print("PARSE=PASS")

    evaluator = LimitEvaluator(contract)
    authorized: List[Utility] = []
    for utility in contract.utilities:
        decision = evaluator.evaluate(utility)
        print(f"AUTHORIZE {utility.id} -> {decision.effect} ({decision.reason})")
        if decision.effect == EFFECT_APPROVAL:
            print("AUTHORIZE=FAIL waiting_for_approval")
            return 1
        if decision.effect != EFFECT_ALLOW:
            print("AUTHORIZE=FAIL")
            return 1
        authorized.append(utility)
    if not authorized:
        print("AUTHORIZE=FAIL no utilities permitted")
        return 1
    status["AUTHORIZE"] = "PASS"
    print("AUTHORIZE=PASS")

    server = None
    thread = None
    if use_mock or not base_url:
        base_url, server, thread = _start_mock()
        print(f"MOCK_BASE_URL={base_url}")

    assert base_url is not None
    resolver = UtilityResolver(base_url)
    reads = [u for u in authorized if u.type == UtilityType.READ]
    if not reads:
        print("HTTP_EXECUTION=FAIL no READ utility authorized")
        return 1

    utility = reads[0]
    binding = resolver.resolve(utility)
    result = binding.execute({})
    http_status = int(result.get("status_code") or 0)
    body = result.get("body")
    err = result.get("error")
    if err or not (200 <= http_status < 300):
        print(f"HTTP_EXECUTION=FAIL status={http_status} error={err}")
        if server is not None:
            server.shutdown()
        return 1
    status["HTTP_EXECUTION"] = "PASS"
    print(f"HTTP_EXECUTION=PASS method={binding.method} path={binding.path} status={http_status}")

    world_state = _services_world_state(body)
    goals_ok = all(GluLessRuntime.evaluate_goal(world_state, goal) for goal in contract.goals)
    evidence_ok = True
    for req in contract.evidence_requirements:
        passed = _evidence_pass(req.assertion, http_status, body, world_state)
        print(f"EVIDENCE {req.id} {'PASS' if passed else 'FAIL'} ({req.assertion})")
        evidence_ok = evidence_ok and passed
        EvidenceBuilder.build(
            kind="state_observation" if passed else "verification_failure",
            claim={"assertion": req.assertion, "passed": passed, "http_status": http_status},
            source_utility=utility.id,
            run_id=f"cli-{uuid4().hex[:8]}",
            contract_id=contract.id,
        )

    if not goals_ok or not evidence_ok:
        print(f"GOAL_EVALUATION=FAIL world_state={json.dumps(world_state, sort_keys=True)}")
        if server is not None:
            server.shutdown()
        return 1

    status["GOAL_EVALUATION"] = "PASS"
    print("GOAL_EVALUATION=PASS")
    print("PROVEN=YES")
    print(f"CONTRACT={contract.id}")
    print(f"WORLD_STATE={json.dumps(world_state, sort_keys=True)}")

    if server is not None:
        server.shutdown()
        if thread is not None:
            thread.join(timeout=2)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gluless", description="GluLess Goal · Limits · Utilities CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    prove_p = sub.add_parser("prove", help="Parse, authorize, execute, and evaluate a .glu Goal")
    prove_p.add_argument(
        "--contract",
        default=os.environ.get(ENV_CONTRACT, ""),
        help=f"Path to .glu contract (or ${ENV_CONTRACT})",
    )
    prove_p.add_argument(
        "--openapi",
        default=os.environ.get(ENV_OPENAPI, ""),
        help=f"Path to OpenAPI YAML (or ${ENV_OPENAPI})",
    )
    prove_p.add_argument(
        "--base-url",
        default=os.environ.get(ENV_BASE_URL, ""),
        help=f"API base URL including version prefix (or ${ENV_BASE_URL})",
    )
    prove_p.add_argument(
        "--mock",
        action="store_true",
        help="Use an ephemeral all-healthy Monitoring mock (default when --base-url is empty)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prove":
        if not args.contract:
            print(f"missing --contract or ${ENV_CONTRACT}", file=sys.stderr)
            return 2
        if not args.openapi:
            print(f"missing --openapi or ${ENV_OPENAPI}", file=sys.stderr)
            return 2
        contract_path = Path(args.contract).expanduser().resolve()
        openapi_path = Path(args.openapi).expanduser().resolve()
        if not contract_path.is_file():
            print(f"contract not found: {contract_path}", file=sys.stderr)
            return 2
        if not openapi_path.is_file():
            print(f"openapi not found: {openapi_path}", file=sys.stderr)
            return 2
        base_url = args.base_url.strip() or None
        return prove(contract_path, openapi_path, base_url, use_mock=bool(args.mock) or base_url is None)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
