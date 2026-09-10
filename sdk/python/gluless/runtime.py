"""GluLess runtime: the next-valid-action loop.

    Observe -> Evaluate Goal -> Propose -> Authorize -> Execute -> Observe ...

Deterministic ownership lives here (limits, evidence, results, events).
Planning is currently trivial: the first READ utility observes, the first
MUTATION utility is proposed. A planner interface replaces that later without
changing the authority path.
"""
import dataclasses
import json
import time
from typing import Any, Callable, Dict, List, Optional

from ag_ui.core import (
    BaseEvent,
    EventType,
    RunAgentInput,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from gluless.bindings import UtilityResolver
from gluless.evidence import Evidence, EvidenceBuilder
from gluless.experience import ExperienceIndex
from gluless.limits import EFFECT_ALLOW, EFFECT_APPROVAL, LimitDecision, LimitEvaluator
from gluless.models import Contract, Goal, UtilityType
from gluless.results import Result, ResultBuilder


class LimitViolationError(Exception):
    pass


class GoalUnsatisfiableError(Exception):
    pass


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(v) for v in obj]
    return obj


class GluLessRuntime:
    def __init__(
        self,
        contract: Contract,
        on_event: Optional[Callable[[BaseEvent], None]] = None,
        thread_id: str = "default-thread",
        run_id: str = "default-run",
        experience_index: Optional[ExperienceIndex] = None,
    ):
        self.contract = contract
        self.on_event = on_event
        self.thread_id = thread_id
        self.run_id = run_id
        self.experience_index = experience_index or ExperienceIndex()
        self.world_state: Dict[str, Any] = {}
        self.limit_decisions: List[LimitDecision] = []
        self.invocations: List[Dict[str, Any]] = []
        self.evidence_list: List[Evidence] = []

    # ------------------------------------------------------------------ events
    def _emit(self, event: BaseEvent) -> None:
        if self.on_event:
            if event.timestamp is None:
                event.timestamp = int(time.time() * 1000)
            self.on_event(event)

    def _step(self, name: str, started: bool) -> None:
        if started:
            self._emit(StepStartedEvent(type=EventType.STEP_STARTED, step_name=name))
        else:
            self._emit(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=name))

    # ------------------------------------------------------------------- goals
    @staticmethod
    def evaluate_goal(state: Dict[str, Any], goal: Goal) -> bool:
        """Evaluate `a.b.c == value` or `a.b.c != value` against observed state.
        Anything else is unsupported and evaluates to False (never to True)."""
        expr = goal.expression
        for op in ("!=", "=="):
            if op in expr:
                key, _, val = expr.partition(op)
                val = val.strip().strip("'\"")
                curr: Any = state
                for part in key.strip().split("."):
                    if isinstance(curr, dict) and part in curr:
                        curr = curr[part]
                    else:
                        return False
                low = val.lower()
                if low in ("true", "false"):
                    equal = bool(curr) if low == "true" else not bool(curr)
                else:
                    equal = str(curr) == val
                return equal if op == "==" else not equal
        return False

    # --------------------------------------------------------------- execution
    def _invoke(self, utility, kind: str, step: int, execute: Callable[[], Dict[str, Any]], method: str, path: str):
        tool_call_id = f"call_{utility.id}_{kind}_{step}"
        self._emit(ToolCallStartEvent(type=EventType.TOOL_CALL_START, tool_call_id=tool_call_id, tool_call_name=utility.id))
        start = time.perf_counter()
        try:
            res = execute()
        except Exception as e:  # noqa: BLE001 - recorded then re-raised
            self.experience_index.record_invocation(utility.id, False, time.perf_counter() - start, str(e))
            raise
        latency = time.perf_counter() - start
        ok = "error" not in res and (res.get("status_code") or 0) < 400
        self.experience_index.record_invocation(utility.id, ok, latency, res.get("error"))
        self.invocations.append(
            {"utility": utility.id, "method": method, "path": path, "status_code": res.get("status_code"), "type": kind}
        )
        self._emit(ToolCallEndEvent(type=EventType.TOOL_CALL_END, tool_call_id=tool_call_id))
        self._emit(
            ToolCallResultEvent(
                type=EventType.TOOL_CALL_RESULT,
                message_id=f"msg_{kind}_{step}",
                tool_call_id=tool_call_id,
                content=json.dumps(res.get("body")),
            )
        )
        if "error" in res:
            raise RuntimeError(f"{kind} failed for {utility.id}: {res['error']}")
        return res

    def _result(self, status: str, details: str, failure: Optional[str] = None) -> Result:
        return ResultBuilder.build(
            run_id=self.run_id,
            contract_id=self.contract.id,
            status=status,
            goal_status={"satisfied": status == "satisfied", "details": details},
            invocations=self.invocations,
            limit_decisions=self.limit_decisions,
            evidence=self.evidence_list,
            failure=failure,
            final_state=self.world_state.copy(),
        )

    def _finish(self, result: Result) -> Result:
        self._emit(
            RunFinishedEvent(type=EventType.RUN_FINISHED, thread_id=self.thread_id, run_id=self.run_id, result=_jsonable(result))
        )
        return result

    def execute_contract(
        self,
        initial_state: Dict[str, Any],
        server_url: Any = None,
        utility_inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        response_transformer: Optional[Callable[[str, Any], Dict[str, Any]]] = None,
        max_steps: int = 5,
        headers: Optional[Dict[str, str]] = None,
    ) -> Result:
        """
        server_url: base URL of the real API, or (test-only) a dict of
                    {utility_id: callable(state) -> body} in-process executors.
        headers:    auth headers sourced externally; never recorded.
        """
        self.world_state = dict(initial_state)
        inputs_map = utility_inputs or {}
        executors = server_url if isinstance(server_url, dict) else None
        resolver = None if executors is not None else UtilityResolver(server_url, headers=headers)
        evaluator = LimitEvaluator(self.contract)

        self._emit(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=self.thread_id,
                run_id=self.run_id,
                input=RunAgentInput(
                    thread_id=self.thread_id, run_id=self.run_id, messages=[], tools=[], context=[], forwarded_props={}
                ),
            )
        )

        reads = [u for u in self.contract.utilities if u.type == UtilityType.READ]
        mutations = [u for u in self.contract.utilities if u.type == UtilityType.MUTATION]

        def run_utility(utility, kind, step):
            if executors is not None:
                def ex():
                    fn = executors.get(utility.id)
                    body = fn(self.world_state) if fn else self.world_state.copy()
                    return {"status_code": 200, "body": body}
                return self._invoke(utility, kind, step, ex, utility.transport.method, utility.transport.path)
            binding = resolver.resolve(utility)
            return self._invoke(
                utility, kind, step, lambda: binding.execute(inputs_map.get(utility.id, {})), binding.method, binding.path
            )

        try:
            self._step("contract.validate", True)
            for limit in self.contract.limits:
                LimitEvaluator.parse_rule(limit.action_pattern)  # fail before any I/O
            self._step("contract.validate", False)

            for step in range(max_steps + 1):
                # Observe
                if reads:
                    self._step("observation.execute", True)
                    res = run_utility(reads[0], "observation", step)
                    body = res.get("body")
                    if response_transformer:
                        self.world_state.update(response_transformer(reads[0].id, body))
                    elif isinstance(body, dict):
                        self.world_state.update(body)
                    self.evidence_list.append(
                        EvidenceBuilder.build(
                            kind="state_observation",
                            claim=self.world_state.copy(),
                            source_utility=reads[0].id,
                            run_id=self.run_id,
                            contract_id=self.contract.id,
                        )
                    )
                    self._step("observation.execute", False)

                # Evaluate
                self._step("goal.evaluate", True)
                self._emit(StateSnapshotEvent(type=EventType.STATE_SNAPSHOT, snapshot=self.world_state))
                satisfied = all(self.evaluate_goal(self.world_state, g) for g in self.contract.goals)
                self._step("goal.evaluate", False)
                if satisfied:
                    return self._finish(self._result("satisfied", "All contract goals met"))
                if step == max_steps:
                    break

                # Propose
                self._step("action.propose", True)
                if not mutations:
                    raise GoalUnsatisfiableError("No mutation utilities available to resolve unsatisfied goals.")
                proposed = mutations[0]
                self._step("action.propose", False)

                # Authorize (deterministic; no mode overrides the decision)
                self._step("action.authorize", True)
                decision = evaluator.evaluate(proposed)
                self.limit_decisions.append(decision)
                self._step("action.authorize", False)
                if decision.effect == EFFECT_APPROVAL:
                    return self._finish(
                        self._result("waiting_for_approval", decision.reason, failure=None)
                    )
                if decision.effect != EFFECT_ALLOW:
                    raise LimitViolationError(decision.reason)

                # Execute
                if executors is not None and proposed.id not in executors:
                    raise RuntimeError(f"No executor registered for {proposed.id}")
                res = run_utility(proposed, "mutation", step)
                if executors is not None and isinstance(res.get("body"), dict):
                    self.world_state.update(res["body"])
                self.evidence_list.append(
                    EvidenceBuilder.build(
                        kind="mutation_action",
                        claim={"utility": proposed.id, "status_code": res.get("status_code"), "response": res.get("body")},
                        source_utility=proposed.id,
                        run_id=self.run_id,
                        contract_id=self.contract.id,
                    )
                )

            raise GoalUnsatisfiableError("Max steps reached without goal satisfaction.")

        except LimitViolationError as e:
            self._emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code=e.__class__.__name__))
            if executors is not None:
                raise
            return self._finish(self._result("blocked", str(e), failure=str(e)))
        except Exception as e:  # noqa: BLE001 - every failure becomes a typed Result
            self._emit(RunErrorEvent(type=EventType.RUN_ERROR, message=str(e), code=e.__class__.__name__))
            return self._result("failed", f"Execution failed: {e}", failure=str(e))
