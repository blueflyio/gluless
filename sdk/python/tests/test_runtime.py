from typing import Any, Dict

import pytest
from ag_ui.core import BaseEvent, EventType

from gluless.models import Contract, Goal, Limit, SideEffectType, Utility, UtilityTransport, UtilityType
from gluless.runtime import GluLessRuntime, LimitViolationError


def test_runtime_success_execution():
    # Define a goal: service.health == healthy
    goal = Goal(id="goal-1", expression="service.health == healthy")

    # Define a utility to update status
    utility = Utility(
        id="deployment.update",
        name="update",
        namespace="deployment",
        description="Updates deployment state",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=UtilityTransport(type="openapi", method="POST", path="/update")
    )

    contract = Contract(
        id="contract-1",
        goals=[goal],
        limits=[Limit(id="permit-update", action_pattern="allow deployment.update")],
        utilities=[utility]
    )

    emitted_events: list[BaseEvent] = []
    def log_event(ev: BaseEvent):
        emitted_events.append(ev)

    runtime = GluLessRuntime(
        contract=contract,
        on_event=log_event,
        thread_id="thread-test",
        run_id="run-test"
    )

    # Initial state is unhealthy
    initial_state = {"service": {"health": "unhealthy"}}

    # Executor sets health to healthy
    def mock_update(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"service": {"health": "healthy"}}

    executors = {
        "deployment.update": mock_update
    }

    res = runtime.execute_contract(initial_state, executors)

    assert res["status"] == "success"
    assert res["final_state"]["service"]["health"] == "healthy"

    # Verify emitted AG-UI events
    event_types = [e.type for e in emitted_events]

    assert EventType.RUN_STARTED in event_types
    assert EventType.STEP_STARTED in event_types
    assert EventType.STATE_SNAPSHOT in event_types
    assert EventType.TOOL_CALL_START in event_types
    assert EventType.TOOL_CALL_END in event_types
    assert EventType.TOOL_CALL_RESULT in event_types
    assert EventType.RUN_FINISHED in event_types
    assert EventType.RUN_ERROR not in event_types


def test_runtime_limit_violation():
    # Define a goal: service.health == healthy
    goal = Goal(id="goal-1", expression="service.health == healthy")

    # Define a utility with infrastructure side effects
    utility = Utility(
        id="deployment.destroy",
        name="destroy",
        namespace="deployment",
        description="Destroys deployment",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.INFRASTRUCTURE,
        transport=UtilityTransport(type="openapi", method="POST", path="/destroy")
    )

    # Limit denies infrastructure side effects
    limit = Limit(id="limit-1", action_pattern="deny infrastructure")

    contract = Contract(
        id="contract-1",
        goals=[goal],
        limits=[limit],
        utilities=[utility]
    )

    emitted_events: list[BaseEvent] = []
    def log_event(ev: BaseEvent):
        emitted_events.append(ev)

    runtime = GluLessRuntime(
        contract=contract,
        on_event=log_event,
        thread_id="thread-test",
        run_id="run-test"
    )

    initial_state = {"service": {"health": "unhealthy"}}
    executors = {
        "deployment.destroy": lambda s: {}
    }

    with pytest.raises(LimitViolationError):
        runtime.execute_contract(initial_state, executors)

    # Verify that a RunErrorEvent was emitted
    event_types = [e.type for e in emitted_events]
    assert EventType.RUN_ERROR in event_types
    error_event = next(e for e in emitted_events if e.type == EventType.RUN_ERROR)
    assert error_event.code == "LimitViolationError"
