"""
GLU Agent  —  v0.2.0
====================

GluLess-native AG-UI agent.  Accepts a GLU contract YAML as the user message,
executes it through the real GluLess SDK pipeline, and streams AG-UI events back.

Architecture
------------
This file is intentionally thin.  Execution logic lives in the SDK at
sdk/python/gluless/.  The agent is responsible for:

  1. Parsing the incoming AG-UI RunAgentInput
  2. Compiling the GLU contract via the SDK Compiler
  3. Loading the Utility Registry by projecting api/openapi.yaml through
     the SDK OpenAPIImporter — the OpenAPI contract is the authoritative
     API definition; the importer projects it into the runtime registry
  4. Running the GluLess five-stage pipeline via ContextResolver +
     LimitEvaluator + ExecutableBinding + EvidenceBuilder
  5. Streaming AG-UI events (STATE_SNAPSHOT / STATE_DELTA / …) back

No utility metadata is hardcoded here.  All utility data is projected
from api/openapi.yaml at startup.  The ExperienceIndex is ephemeral
per-process (no fake reliability scores injected).

Env vars
--------
  API_URL          Base URL of the target API  (default: http://localhost:8000/v0)
  API_TOKEN        Optional API key for X-API-Token header
  OPENAPI_SPEC     Path to openapi.yaml (default: auto-discovered from repo root)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import traceback
from pathlib import Path
from typing import Any, AsyncIterator

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

# ── GluLess SDK ──────────────────────────────────────────────────
from gluless.models import (
    Contract,
    EvidenceRequirement,
    Goal,
    Limit,
    SideEffectType,
    Utility,
    UtilityType,
)
from gluless.importers.openapi import OpenAPIImporter
from gluless.registry import UtilityRegistry
from gluless.context import ContextResolver
from gluless.limits import LimitEvaluator
from gluless.bindings import UtilityResolver
from gluless.evidence import EvidenceBuilder
from gluless.experience import ExperienceIndex

# ── Constants ────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]  # …/POCs/Gluless
_OPENAPI_DEFAULT = _REPO_ROOT / "api" / "openapi.yaml"
_OPENAPI_PATH = Path(os.environ.get("OPENAPI_SPEC", str(_OPENAPI_DEFAULT)))
_API_URL   = os.environ.get("API_URL",   "http://localhost:8000/v0").rstrip("/")
_API_TOKEN = os.environ.get("API_TOKEN", "")
_AGENT_VERSION = "0.2.0"

# ── Registry bootstrap ────────────────────────────────────────────
# Projection: OpenAPI contract → OpenAPIImporter → UtilityRegistry
# The openapi.yaml x-gluless-name / x-gluless-type / x-gluless-side-effects
# extensions are consumed here.  The result is the per-process runtime index.
def _build_registry() -> tuple[UtilityRegistry, list[Utility]]:
    """
    Project Utility objects from api/openapi.yaml.

    Returns (registry, projected_utilities).  Any operation annotated with
    x-gluless-exclude: true (e.g. /health) is present in the OpenAPI spec
    but intentionally absent from the registry.
    """
    spec_text = _OPENAPI_PATH.read_text(encoding="utf-8")
    raw_doc   = yaml.safe_load(spec_text)

    importer   = OpenAPIImporter()
    utilities  = importer.import_spec(spec_text)

    # Remove excluded utilities (x-gluless-exclude: true on the operation).
    # Collect excluded operationIds from the raw document first.
    excluded_op_ids: set[str] = set()
    for path_item in raw_doc.get("paths", {}).values():
        for key, operation in path_item.items():
            if key.lower() in ("parameters", "$ref") or not isinstance(operation, dict):
                continue
            if operation.get("x-gluless-exclude"):
                op_id = operation.get("operationId")
                if op_id:
                    excluded_op_ids.add(op_id.lower())

    # The OpenAPIImporter assigns utility.id from x-gluless-name when present.
    # For operations lacking x-gluless-name (e.g. /health), the id is derived
    # from the namespace + path + method.  We match by operationId suffix in
    # the derived name (the importer lowercases it).
    #
    # operationId "healthCheck" → derived name ends in "health.list" or similar.
    # We exclude conservatively: keep only utilities that have an x-gluless-name,
    # i.e. whose id starts with the x-provider-name AND whose
    # operationId is NOT in the excluded set.

    # Build a map: lowercased x-gluless-name value → True (present in spec)
    glu_named: set[str] = set()
    for path_item in raw_doc.get("paths", {}).values():
        for key, operation in path_item.items():
            if isinstance(operation, dict):
                name = operation.get("x-gluless-name", "")
                if name:
                    glu_named.add(name.lower())

    # Keep only utilities that were explicitly named via x-gluless-name
    filtered = [u for u in utilities if u.id.lower() in glu_named]

    # Register each projected utility — ephemeral registry (no persistence path)
    registry = UtilityRegistry(registry_path=":memory:")
    import hashlib
    spec_digest = hashlib.sha256(spec_text.encode()).hexdigest()[:16]

    for util in filtered:
        registry.register(
            utility=util,
            source_uri=str(_OPENAPI_PATH),
            source_digest=spec_digest,
            source_version=raw_doc.get("info", {}).get("version", "0.0.0"),
            semantic_capabilities={
                "domain":    _capability_domain(util),
                "resource":  util.name.split(".")[0],
                "capability": _capability_name(util),
            },
        )

    return registry, filtered


def _capability_domain(u: Utility) -> str:
    """
    Map a Utility to a semantic capability domain.

    Derives the domain from the resource segment of the utility ID
    (everything between the namespace and the final verb segment).

    e.g.:
      Monitoring.services.list   → "services"
      Monitoring.service.create  → "service"
      Monitoring.sessions.nudge  → "sessions"
      Work.tasks.claim           → "tasks"
    """
    parts = u.id.split(".")
    # parts[0] = namespace, parts[-1] = verb, parts[1:-1] = resource path
    if len(parts) >= 3:
        return ".".join(parts[1:-1]).lower()
    if len(parts) == 2:
        return parts[1].lower()
    return u.namespace.lower()


def _capability_name(u: Utility) -> str:
    """Derive a dot-notation capability name from utility type + domain."""
    domain = _capability_domain(u)
    op = "read" if u.type == UtilityType.READ else u.side_effects.value
    return f"{domain}.{op}"


# Boot-time registry projection
try:
    _REGISTRY, _PROJECTED_UTILITIES = _build_registry()
    _REGISTRY_COUNT = len(_PROJECTED_UTILITIES)
except Exception as _exc:
    _REGISTRY = None  # type: ignore[assignment]
    _PROJECTED_UTILITIES = []
    _REGISTRY_COUNT = 0
    _REGISTRY_ERROR = str(_exc)
else:
    _REGISTRY_ERROR = None

# ── Per-process ExperienceIndex ───────────────────────────────────
# Ephemeral — no fake prior-run reliability scores.
_EXPERIENCE = ExperienceIndex(index_path="/tmp/gluless_experience.json")

# ── FastAPI app ───────────────────────────────────────────────────
app = FastAPI(
    title="GLU Agent",
    version=_AGENT_VERSION,
    description="GluLess-native AG-UI agent.  Contract → RESOLVE → FILTER → AUTHORIZE → EXECUTE → VERIFY.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── AG-UI Event helpers ───────────────────────────────────────────
def _ts() -> int:
    return int(time.time() * 1000)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _run_started(thread_id: str, run_id: str) -> str:
    return _sse({"type": "RUN_STARTED", "threadId": thread_id, "runId": run_id, "timestamp": _ts()})


def _run_finished(thread_id: str, run_id: str, warning: str | None = None) -> str:
    e: dict[str, Any] = {"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id, "timestamp": _ts()}
    if warning:
        e["warning"] = warning
    return _sse(e)


def _run_error(thread_id: str, run_id: str, code: str, message: str) -> str:
    return _sse({"type": "RUN_ERROR", "threadId": thread_id, "runId": run_id,
                 "code": code, "message": message, "timestamp": _ts()})


def _text_chunk(message_id: str, delta: str) -> str:
    return _sse({"type": "TEXT_MESSAGE_CHUNK", "messageId": message_id, "delta": delta, "timestamp": _ts()})


def _text_start(message_id: str) -> str:
    return _sse({"type": "TEXT_MESSAGE_START", "messageId": message_id, "timestamp": _ts()})


def _text_end(message_id: str) -> str:
    return _sse({"type": "TEXT_MESSAGE_END", "messageId": message_id, "timestamp": _ts()})


def _snapshot(thread_id: str, run_id: str, snapshot: dict) -> str:
    return _sse({"type": "STATE_SNAPSHOT", "threadId": thread_id, "runId": run_id,
                 "snapshot": snapshot, "timestamp": _ts()})


def _delta(thread_id: str, run_id: str, ops: list[dict]) -> str:
    return _sse({"type": "STATE_DELTA", "threadId": thread_id, "runId": run_id,
                 "delta": ops, "timestamp": _ts()})


# ── State serialisers ─────────────────────────────────────────────
def _ser_utility(u: Utility) -> dict:
    return {
        "id":          u.id,
        "type":        u.type.value,
        "sideEffects": u.side_effects.value,
        "transport":   {"method": u.transport.method, "path": u.transport.path},
    }


def _ser_limit(l: Limit) -> dict:
    return {"id": l.id, "pattern": l.action_pattern, "description": l.description or ""}


def _ser_goal(g: Goal) -> dict:
    return {"id": g.id, "expression": g.expression, "description": g.description or ""}


def _ser_evidence_requirement(e: EvidenceRequirement) -> dict:
    return {"id": e.id, "assertion": e.assertion, "description": e.description or ""}


# ── Contract compiler ─────────────────────────────────────────────
def _compile_contract(yaml_text: str) -> Contract:
    """
    Parse a GLU contract YAML into a Contract IR.

    The 'utilities' list in the contract contains string IDs.  We resolve
    each ID against the projected registry.  Only IDs present in the
    registry are accepted — no phantom utilities.
    """
    raw = yaml.safe_load(yaml_text)

    goals = [
        Goal(id=g["id"], expression=g["expression"], description=g.get("description"))
        for g in raw.get("goals", [])
    ]

    limits = [
        Limit(id=l["id"], action_pattern=l["action_pattern"], description=l.get("description"))
        for l in raw.get("limits", [])
    ]

    utility_ids: list[str] = raw.get("utilities", [])
    utilities: list[Utility] = []
    for uid in utility_ids:
        registry_key = f"utility://{uid.split('.')[0].lower()}/{uid.split('.', 1)[1].lower()}"
        resolved = _REGISTRY.resolve(registry_key)
        if resolved:
            utilities.append(resolved)
        else:
            # Fallback: search by operation_id
            for reg_data in _REGISTRY.utilities.values():
                if reg_data.get("operation_id", "").lower() == uid.lower():
                    resolved = _REGISTRY.resolve(reg_data["utility_id"])
                    if resolved:
                        utilities.append(resolved)
                    break

    evidence_reqs = [
        EvidenceRequirement(id=e["id"], assertion=e["assertion"], description=e.get("description"))
        for e in raw.get("evidence_requirements", [])
    ]

    return Contract(
        id=raw.get("id", "anonymous"),
        goals=goals,
        limits=limits,
        utilities=utilities,
        evidence_requirements=evidence_reqs,
    )


# ── Goal predicate evaluator ──────────────────────────────────────
def _evaluate_goal(goal: Goal, world_state: dict) -> bool:
    """
    Evaluate a goal expression against world state.

    Supports:
      services.listed == true  →  world_state["services"]["listed"] == True
      tasks.claimed == true    →  world_state["tasks"]["claimed"] == True
    """
    expr = goal.expression.strip()

    if "==" in expr:
        lhs, rhs = [x.strip() for x in expr.split("==", 1)]
        rhs_clean = rhs.strip("\"'")

        # Traverse dotted path
        curr: Any = world_state
        for part in lhs.split("."):
            if isinstance(curr, dict) and part in curr:
                curr = curr[part]
            elif isinstance(curr, list):
                # list means "has items" — check count predicate
                curr = len(curr) > 0
                break
            else:
                return False

        if rhs_clean.lower() == "true":
            return bool(curr)
        if rhs_clean.lower() == "false":
            return not bool(curr)
        return str(curr) == rhs_clean

    return False


def _evaluate_evidence(
    req: EvidenceRequirement,
    http_status: int,
    body: Any,
    world_state: dict,
) -> dict:
    """
    Evaluate a single evidence requirement.

    Returns a dict with: requirementId, assertion, passed, httpStatus,
    detail — suitable for UI rendering and the SDK EvidenceBuilder.

    Supported assertions (matched as substrings, case-insensitive):
      response.status == 200
      response.schema valid        — any non-empty array of objects
      items observed / count > 0   — body is non-empty list
      <key>.listed == true         — world_state key resolution
    """
    assertion = req.assertion.strip()
    assertion_lower = assertion.lower()
    passed = False
    detail = ""

    if "response.status == 200" in assertion_lower:
        passed = http_status == 200
        detail = f"HTTP {http_status}"

    elif "response.schema valid" in assertion_lower or "schema_valid" in assertion_lower:
        # Accept any array of dicts as valid schema
        if isinstance(body, list) and len(body) > 0 and all(isinstance(item, dict) for item in body):
            passed = True
            detail = f"array of {len(body)} objects"
        elif isinstance(body, list) and len(body) == 0:
            passed = False
            detail = "empty array"
        else:
            passed = False
            detail = f"unexpected response type: {type(body).__name__}"

    elif any(kw in assertion_lower for kw in ("items observed", "count > 0", "len(")):
        count = len(body) if isinstance(body, list) else 0
        passed = count > 0
        detail = f"{count} item(s) in response"

    elif "==" in assertion_lower:
        # Generic goal predicate evaluation against world state
        passed = _evaluate_goal(Goal(id="_inline", expression=assertion), world_state)
        detail = "predicate evaluated against world state"

    else:
        # Fallback: HTTP 200 + non-empty body
        passed = http_status == 200 and bool(body)
        detail = f"HTTP {http_status}, body={'non-empty' if body else 'empty'}"

    return {
        "requirementId": req.id,
        "assertion":     req.assertion,
        "passed":        passed,
        "httpStatus":    http_status,
        "detail":        detail,
    }


# ── Main execution pipeline ───────────────────────────────────────
async def _run_contract(
    thread_id: str,
    run_id:    str,
    contract:  Contract,
) -> AsyncIterator[str]:
    """
    Five-stage GluLess pipeline emitting AG-UI events.

    RESOLVE → FILTER → AUTHORIZE → EXECUTE → VERIFY
    """
    mid = f"msg-{run_id[:8]}"

    # ── Initial state snapshot ─────────────────────────────────────
    initial_state: dict[str, Any] = {
        "contractId":         contract.id,
        "phase":              "compiling",
        "goals":              [_ser_goal(g) for g in contract.goals],
        "limits":             [_ser_limit(l) for l in contract.limits],
        "utilities":          [_ser_utility(u) for u in contract.utilities],
        "plan":               [],
        "observations":       [],
        "evidence":           [],
        "decision_paths":     [],
        "context_projection": {
            "registry_total":   _REGISTRY_COUNT,
            "goal_compatible":  0,
            "limit_permitted":  0,
        },
        "error": None,
    }

    yield _snapshot(thread_id, run_id, initial_state)
    await asyncio.sleep(0.05)

    # ─────────────────────────────────────────────────────────────────
    # STAGE 1 — RESOLVE
    # ─────────────────────────────────────────────────────────────────
    yield _text_start(mid)
    yield _text_chunk(mid, f"⚙️  Compiling contract `{contract.id}`…\n")
    yield _text_chunk(mid, f"✅ Registry: {_REGISTRY_COUNT} utilit{'y' if _REGISTRY_COUNT == 1 else 'ies'} loaded from api/openapi.yaml\n")

    yield _delta(thread_id, run_id, [{"op": "replace", "path": "/phase", "value": "resolving"}])
    await asyncio.sleep(0.1)

    # Resolve all registry utilities that are relevant to any goal keyword
    all_registry_utilities: list[Utility] = []
    for reg_data in _REGISTRY.utilities.values():
        resolved = _REGISTRY.resolve(reg_data["utility_id"])
        if resolved:
            all_registry_utilities.append(resolved)

    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/context_projection/registry_total", "value": len(all_registry_utilities)},
    ])

    # ─────────────────────────────────────────────────────────────────
    # STAGE 2 — FILTER (goal-compatible candidates)
    # ─────────────────────────────────────────────────────────────────
    yield _delta(thread_id, run_id, [{"op": "replace", "path": "/phase", "value": "filtering"}])
    await asyncio.sleep(0.05)

    # Goal-domain → capability-domain matching.
    # Extract the resource prefix from each goal expression's LHS.
    # e.g. "services.listed == true"  → LHS = "services.listed" → domain prefix = "services"
    #      "tasks.claimed == true"    → LHS = "tasks.claimed"   → domain prefix = "tasks"
    goal_domains: set[str] = set()
    for goal in contract.goals:
        expr = goal.expression.strip().lower()
        if "==" in expr:
            lhs = expr.split("==")[0].strip()
            # Take the first segment of the dotted path as the domain
            goal_domains.add(lhs.split(".")[0])

    # Filter registry utilities whose capability domain intersects goal domains
    goal_compatible: list[Utility] = []
    for u in all_registry_utilities:
        dom = _capability_domain(u)  # e.g. "services", "service", "sessions"
        if dom in goal_domains:
            goal_compatible.append(u)

    yield _text_chunk(
        mid,
        f"🧠 FILTER: {len(goal_compatible)}/{len(all_registry_utilities)} utilities "
        f"goal-compatible (domain: {', '.join(goal_domains) or '—'})\n",
    )
    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/context_projection/goal_compatible", "value": len(goal_compatible)},
    ])

    # ─────────────────────────────────────────────────────────────────
    # STAGE 3 — AUTHORIZE (limit evaluation)
    # ─────────────────────────────────────────────────────────────────
    yield _delta(thread_id, run_id, [{"op": "replace", "path": "/phase", "value": "authorizing"}])
    await asyncio.sleep(0.05)

    evaluator = LimitEvaluator(contract)
    decision_paths: list[dict] = []
    authorized: list[Utility] = []

    for u in goal_compatible:
        decision = evaluator.evaluate(u)
        decision_paths.append({
            "utilityId":  u.id,
            "decision":   decision.effect,
            "reason":     decision.reason,
            "type":       u.type.value,
            "sideEffects": u.side_effects.value,
        })
        if decision.effect == "allow":
            authorized.append(u)
            yield _text_chunk(mid, f"   ✅ AUTHORIZE {u.id}  ({decision.reason})\n")
        else:
            yield _text_chunk(mid, f"   ✕  DENY  {u.id}  ({decision.reason})\n")

    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/decision_paths",                       "value": decision_paths},
        {"op": "replace", "path": "/context_projection/limit_permitted",   "value": len(authorized)},
        {"op": "replace", "path": "/plan",                                 "value": [u.id for u in authorized]},
    ])

    if not authorized:
        # No utility survived limits — unresolved
        err_msg = "No utility permitted after limit evaluation"
        yield _text_chunk(mid, f"⚠️  {err_msg}\n")
        yield _text_end(mid)
        yield _delta(thread_id, run_id, [
            {"op": "replace", "path": "/phase", "value": "unresolved"},
            {"op": "replace", "path": "/error", "value": err_msg},
        ])
        yield _run_finished(thread_id, run_id, warning=err_msg)
        return

    # ─────────────────────────────────────────────────────────────────
    # STAGE 4 — EXECUTE
    # ─────────────────────────────────────────────────────────────────
    yield _delta(thread_id, run_id, [{"op": "replace", "path": "/phase", "value": "executing"}])

    # Auth header value comes from the environment (sourced by the operator from an
    # external secret provider); the resolver sends it and never records it.
    resolver = UtilityResolver(_API_URL, headers={"X-API-Token": _API_TOKEN} if _API_TOKEN else None)
    observations: list[dict] = []
    world_state: dict[str, Any] = {}
    execution_http_status: int = 0
    execution_body: Any = None
    execution_error: str | None = None

    for u in authorized:
        binding = resolver.resolve(u)
        yield _text_chunk(mid, f"▶️  EXECUTE {u.id}  →  {binding.method} {_API_URL}{binding.path}\n")

        start = time.perf_counter()
        result = await asyncio.get_event_loop().run_in_executor(None, binding.execute, {})
        latency = time.perf_counter() - start

        http_status: int = result.get("status_code", 0)
        body: Any = result.get("body")
        err: str | None = result.get("error")

        success = err is None and 200 <= http_status < 300
        _EXPERIENCE.record_invocation(u.id, success, latency, err)

        observations.append({
            "utilityId":  u.id,
            "method":     binding.method,
            "path":       binding.path,
            "httpStatus": http_status,
            "latencyMs":  round(latency * 1000),
            "success":    success,
            "error":      err,
        })

        if success:
            execution_http_status = http_status
            execution_body = body
            yield _text_chunk(mid, f"   ✅ HTTP {http_status}  ({round(latency * 1000)}ms)\n")

            # Update world state — derive key from goal expression LHS root
            # e.g. "services.listed == true" → world_state["services"]["listed"] = True
            if isinstance(body, list):
                # Use the first goal's LHS root as the state key
                state_key = "items"
                if contract.goals:
                    expr = contract.goals[0].expression.strip().lower()
                    if "==" in expr:
                        lhs = expr.split("==")[0].strip()
                        state_key = lhs.split(".")[0]
                world_state[state_key] = {"listed": len(body) > 0, "items": body, "count": len(body)}
        else:
            execution_http_status = http_status
            execution_error = err or f"HTTP {http_status}"
            yield _text_chunk(mid, f"   ⚠️  {execution_error}\n")

    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/observations", "value": observations},
    ])

    # ─────────────────────────────────────────────────────────────────
    # STAGE 5 — VERIFY
    # ─────────────────────────────────────────────────────────────────
    yield _delta(thread_id, run_id, [{"op": "replace", "path": "/phase", "value": "verifying"}])
    await asyncio.sleep(0.05)

    evidence_results: list[dict] = []

    # Fall back to default evidence requirements if none declared in contract
    evidence_reqs = contract.evidence_requirements or [
        EvidenceRequirement(id="ev-http-ok",      assertion="response.status == 200"),
        EvidenceRequirement(id="ev-schema-valid", assertion="response.schema valid"),
        EvidenceRequirement(id="ev-items",        assertion="items observed"),
    ]

    all_passed = True
    for req in evidence_reqs:
        ev_result = _evaluate_evidence(req, execution_http_status, execution_body, world_state)
        evidence_results.append(ev_result)

        # Build cryptographic evidence record via SDK
        sdk_evidence = EvidenceBuilder.build(
            kind="state_observation" if ev_result["passed"] else "verification_failure",
            claim={
                "assertion":   req.assertion,
                "passed":      ev_result["passed"],
                "http_status": execution_http_status,
            },
            source_utility=authorized[0].id if authorized else "none",
            run_id=run_id,
            contract_id=contract.id,
        )

        if ev_result["passed"]:
            yield _text_chunk(mid, f"   ✅ {req.assertion}  PASS\n")
        else:
            yield _text_chunk(mid, f"   ❌ {req.assertion}  FAIL\n")
            all_passed = False

    # Evaluate goal predicates
    goal_satisfied = all(
        _evaluate_goal(g, world_state) for g in contract.goals
    )

    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/evidence", "value": evidence_results},
    ])

    # ─────────────────────────────────────────────────────────────────
    # RESULT
    # ─────────────────────────────────────────────────────────────────
    if execution_error:
        final_phase = "unresolved"
        warning = f"Execution failed: {execution_error}"
        yield _text_chunk(mid, f"\n⚠️  Phase: {final_phase}  │  Observations: {len(observations)}  │  Evidence: {len(evidence_results)}\n")
    elif goal_satisfied and all_passed:
        final_phase = "proven"
        warning = None
        yield _text_chunk(mid, f"\n✅ Phase: {final_phase}  │  Goal satisfied  │  Evidence: {len(evidence_results)}\n")
    else:
        final_phase = "unresolved"
        warning = "Goal predicate not satisfied or evidence incomplete"
        yield _text_chunk(mid, f"\n⚠️  Phase: {final_phase}  │  Evidence: {len(evidence_results)}\n")

    yield _text_end(mid)

    yield _delta(thread_id, run_id, [
        {"op": "replace", "path": "/phase", "value": final_phase},
    ])

    yield _run_finished(thread_id, run_id, warning=warning)


# ── HTTP endpoints ────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok" if _REGISTRY else "degraded",
        "version": _AGENT_VERSION,
        "registry": _REGISTRY_COUNT,
        "apiUrl": _API_URL,
        "openapiSpec": str(_OPENAPI_PATH),
        "registryError": _REGISTRY_ERROR,
    }


@app.get("/utilities")
def list_utilities():
    """
    List all utilities currently projected into the runtime registry.

    Returns the canonical projected utility list — the full set available
    for goal-filtering and limit-authorization before any contract runs.
    This is a read-only introspection endpoint; it does not execute any utility.
    """
    if _REGISTRY is None:
        return {"error": "registry not loaded", "detail": _REGISTRY_ERROR, "utilities": []}

    utilities = []
    for reg_id, ut_data in _REGISTRY.utilities.items():
        utilities.append({
            "registryId":  reg_id,
            "utilityId":   ut_data["operation_id"],
            "type":        ut_data["type"],
            "sideEffects": ut_data["side_effect"]["declared"],
            "transport": {
                "method": ut_data["transport"]["method"],
                "path":   ut_data["transport"]["path"],
            },
            "domain":      ut_data["semantic_capabilities"].get("domain", ""),
            "sourceUri":   ut_data["source_uri"],
        })
    return {"count": len(utilities), "utilities": utilities}


@app.get("/registry")
def registry_dump():
    """
    Return the full runtime registry as JSON.

    Introspection endpoint for debugging importer projections. Shows every
    field stored per utility including transport, side-effect tracking,
    auth requirements, and semantic capability metadata.
    Not intended for production use.
    """
    if _REGISTRY is None:
        return {"error": "registry not loaded", "detail": _REGISTRY_ERROR}
    return {"count": len(_REGISTRY.utilities), "registry": _REGISTRY.utilities}


@app.get("/connections")
def list_connections():
    """
    List active transport connections (base URLs) the agent can reach.

    In the POC this is a single target (the API_URL from env).
    In a production GluLess runtime this would enumerate all registered
    connection descriptors (one per imported API spec or MCP server).
    """
    connections = []
    if _REGISTRY:
        # Derive distinct servers from projected utilities
        seen: set[str] = set()
        for ut_data in _REGISTRY.utilities.values():
            server = _API_URL
            if server not in seen:
                seen.add(server)
                connections.append({
                    "id":       "default",
                    "type":     "http",
                    "baseUrl":  server,
                    "specUri":  str(_OPENAPI_PATH),
                    "status":   "configured",
                })
    return {"count": len(connections), "connections": connections}


@app.post("/agent")
async def agent_endpoint(request: Request) -> StreamingResponse:
    body = await request.json()
    thread_id = body.get("threadId", "default-thread")
    run_id    = body.get("runId",    "default-run")

    # Extract contract YAML from the last user message
    messages = body.get("messages", [])
    contract_yaml: str | None = None
    for msg in reversed(messages):
        if msg.get("role") == "user" and msg.get("content", "").strip():
            contract_yaml = msg["content"].strip()
            break

    async def stream() -> AsyncIterator[str]:
        if _REGISTRY is None:
            yield _run_started(thread_id, run_id)
            yield _run_error(thread_id, run_id, "REGISTRY_LOAD_ERROR",
                             f"Registry failed to load: {_REGISTRY_ERROR}")
            return

        yield _run_started(thread_id, run_id)

        if not contract_yaml:
            yield _run_error(thread_id, run_id, "NO_CONTRACT",
                             "No contract YAML found in messages[].content")
            return

        try:
            contract = _compile_contract(contract_yaml)
        except Exception as exc:
            yield _run_error(thread_id, run_id, "COMPILE_ERROR", str(exc))
            return

        try:
            async for chunk in _run_contract(thread_id, run_id, contract):
                yield chunk
                await asyncio.sleep(0)  # allow event loop to breathe
        except Exception as exc:
            tb = traceback.format_exc()
            yield _run_error(thread_id, run_id, "RUNTIME_ERROR", f"{exc}\n\n{tb}")

    return StreamingResponse(stream(), media_type="text/event-stream")
