import os
import tempfile

import pytest

from gluless.context import ContextResolver
from gluless.experience import ExperienceIndex
from gluless.models import Contract, Goal, Limit, SideEffectType, Utility, UtilityTransport, UtilityType
from gluless.registry import UtilityRegistry


@pytest.fixture
def temp_files():
    fd1, reg_path = tempfile.mkstemp()
    os.close(fd1)
    fd2, exp_path = tempfile.mkstemp()
    os.close(fd2)
    yield reg_path, exp_path
    if os.path.exists(reg_path):
        os.remove(reg_path)
    if os.path.exists(exp_path):
        os.remove(exp_path)

def test_resolver_limits_enforcement(temp_files):
    reg_path, exp_path = temp_files
    registry = UtilityRegistry(registry_path=reg_path)
    exp_index = ExperienceIndex(index_path=exp_path)

    # 1. Register a mutation utility
    t = UtilityTransport(type="openapi", method="POST", path="/destroy")
    utility = Utility(
        id="GasCity.cities.destroy",
        name="cities.destroy",
        namespace="GasCity",
        description="Destroy city rig",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.INFRASTRUCTURE,
        transport=t
    )
    registry.register(utility, "file:///mock/openapi.yaml", "digest1")

    # 2. Record historical successes in experience index
    exp_index.record_invocation(utility.id, success=True, latency=0.1)
    exp_index.record_invocation(utility.id, success=True, latency=0.08)

    # 3. Create contract with a strict DENY limit
    contract = Contract(
        id="test-limits-contract",
        goals=[Goal(id="g1", expression="cities.blucity.health == healthy")],
        limits=[Limit(id="l1", action_pattern="deny infrastructure")],
        utilities=[utility]
    )

    resolver = ContextResolver(registry, exp_index)
    projection = resolver.resolve_context(contract, current_observations={})

    # The utility must be excluded because limits deny infrastructure side-effects
    # Enforces: PAST_SUCCESS != CURRENT_AUTHORITY
    assert len(projection.utilities) == 0

def test_resolver_experience_ranking(temp_files):
    reg_path, exp_path = temp_files
    registry = UtilityRegistry(registry_path=reg_path)
    exp_index = ExperienceIndex(index_path=exp_path)

    # Register Utility A (high-performance)
    t_a = UtilityTransport(type="openapi", method="POST", path="/a")
    utility_a = Utility(
        id="GasCity.action.a",
        name="action.a",
        namespace="GasCity",
        description="Option A",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=t_a
    )
    registry.register(utility_a, "file:///mock/openapi.yaml", "digest")

    # Register Utility B (low-performance / high latency)
    t_b = UtilityTransport(type="openapi", method="POST", path="/b")
    utility_b = Utility(
        id="GasCity.action.b",
        name="action.b",
        namespace="GasCity",
        description="Option B",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=t_b
    )
    registry.register(utility_b, "file:///mock/openapi.yaml", "digest")

    # Record stats
    # A has 100% success rate, 50ms latency
    exp_index.record_invocation(utility_a.id, success=True, latency=0.05)
    exp_index.record_invocation(utility_a.id, success=True, latency=0.05)

    # B has 50% success rate, 500ms latency
    exp_index.record_invocation(utility_b.id, success=True, latency=0.5)
    exp_index.record_invocation(utility_b.id, success=False, latency=0.5)

    contract = Contract(
        id="test-ranking-contract",
        goals=[Goal(id="g1", expression="action.status == achieved")],
        limits=[Limit(id="l1", action_pattern="allow *")],
        utilities=[utility_a, utility_b]
    )

    resolver = ContextResolver(registry, exp_index)
    projection = resolver.resolve_context(contract, current_observations={})

    # Both utilities should be allowed
    assert len(projection.utilities) == 2

    # Utility A must be ranked first due to higher success rate / lower latency
    assert projection.utilities[0].id == "GasCity.action.a"
    assert projection.utilities[1].id == "GasCity.action.b"

def test_resolver_projection_discardability(temp_files):
    reg_path, exp_path = temp_files
    registry = UtilityRegistry(registry_path=reg_path)
    exp_index = ExperienceIndex(index_path=exp_path)

    t = UtilityTransport(type="openapi", method="POST", path="/nudge")
    utility = Utility(
        id="GasCity.action.nudge",
        name="action.nudge",
        namespace="GasCity",
        description="Nudge Option",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=t
    )
    registry.register(utility, "file:///mock/openapi.yaml", "digest")

    contract = Contract(
        id="test-discard-contract",
        goals=[Goal(id="g1", expression="action.status == nudge")],
        limits=[],
        utilities=[utility]
    )

    resolver = ContextResolver(registry, exp_index)
    projection = resolver.resolve_context(contract, current_observations={})

    # Mutate the projection projection
    projection.utilities.clear()

    # Assert master registry is not mutated/changed
    assert len(registry.utilities) == 1
