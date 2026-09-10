import pytest

from gluless.compiler import CompileError, GluLessCompiler
from gluless.models import SideEffectType, Utility, UtilityTransport, UtilityType


@pytest.fixture
def available_utils():
    return [
        Utility(
            id="deployment.update",
            name="update",
            namespace="deployment",
            description="Update deployment status",
            type=UtilityType.MUTATION,
            side_effects=SideEffectType.UPDATE,
            transport=UtilityTransport(type="openapi", method="POST", path="/update")
        ),
        Utility(
            id="deployment.read",
            name="read",
            namespace="deployment",
            description="Read deployment status",
            type=UtilityType.READ,
            side_effects=SideEffectType.READ,
            transport=UtilityTransport(type="openapi", method="GET", path="/status")
        )
    ]

def test_compile_valid_contract(available_utils):
    yaml_src = """
    id: test-pipeline
    goals:
      - id: target-healthy
        expression: service.health == healthy
        description: Ensure the service reaches healthy state
      - id: target-version
        expression: service.version == v1.2.0
    limits:
      - id: deny-deletion
        action_pattern: deny delete
      - id: deny-infra
        action_pattern: deny infrastructure
    evidence_requirements:
      - id: commit-check
        assertion: git.commit_exists(merge_commit_sha)
    utilities:
      - deployment.update
      - deployment.read
    """

    contract = GluLessCompiler.compile_yaml(yaml_src, available_utilities=available_utils)

    assert contract.id == "test-pipeline"
    assert len(contract.goals) == 2
    assert contract.goals[0].expression == "service.health == healthy"
    assert len(contract.limits) == 2
    assert contract.limits[0].action_pattern == "deny delete"
    assert len(contract.evidence_requirements) == 1
    assert contract.evidence_requirements[0].assertion == "git.commit_exists(merge_commit_sha)"
    assert len(contract.utilities) == 2
    assert contract.utilities[0].id == "deployment.update"

def test_compile_missing_id():
    yaml_src = """
    goals:
      - id: target-healthy
        expression: service.health == healthy
    """
    with pytest.raises(CompileError, match="Contract 'id' is required"):
        GluLessCompiler.compile_yaml(yaml_src)

def test_compile_missing_goal_expression():
    yaml_src = """
    id: contract-1
    goals:
      - id: target-healthy
        description: No expression field
    """
    with pytest.raises(CompileError, match="is missing required fields"):
        GluLessCompiler.compile_yaml(yaml_src)

def test_compile_unresolved_utility(available_utils):
    yaml_src = """
    id: test-contract
    goals:
      - id: target-healthy
        expression: service.health == healthy
    utilities:
      - deployment.unresolved_action
    """
    with pytest.raises(CompileError, match="could not be resolved"):
        GluLessCompiler.compile_yaml(yaml_src, available_utilities=available_utils)
