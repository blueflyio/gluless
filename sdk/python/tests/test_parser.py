"""Happy-path syntax tests for the `.glu` parser.

Each test covers one block or selector form from the README. No semantic
validation is asserted — only that source maps onto `models.py` IR.
"""

import pytest

from gluless.limits import LimitEvaluator
from gluless.models import SideEffectType, UtilityType
from gluless.parser import ParseError, parse

README_GOAL = """
goal ServicesHealthy {
    target:
        services.healthy == true

    limits:
        deny *
        allow Monitoring.services.list

    utilities:
        Monitoring.services.list

    evidence:
        response.status == 200
        response.schema valid
        services observed
}
"""

STANDALONE_LIMITS = """
limits {
    deny *
    allow Work.tasks.read
    allow Work.tasks.claim
    require approval for Deployment.promote
    deny Infrastructure.destroy
}
"""


def test_goal_block_maps_name_and_target():
    contract = parse(README_GOAL)
    assert contract.id == "ServicesHealthy"
    assert len(contract.goals) == 1
    assert contract.goals[0].id == "ServicesHealthy"
    assert contract.goals[0].expression == "services.healthy == true"


def test_nested_limits_preserve_declaration_order():
    contract = parse(README_GOAL)
    assert [limit.action_pattern for limit in contract.limits] == [
        "deny *",
        "allow Monitoring.services.list",
    ]
    assert contract.limits[0].id == "limit-1"
    assert contract.limits[1].id == "limit-2"


def test_utilities_block_emits_unresolved_stubs():
    contract = parse(README_GOAL)
    assert len(contract.utilities) == 1
    utility = contract.utilities[0]
    assert utility.id == "Monitoring.services.list"
    assert utility.namespace == "Monitoring"
    assert utility.name == "services.list"
    assert utility.type == UtilityType.READ
    assert utility.side_effects == SideEffectType.UNKNOWN
    assert utility.transport.type == "unresolved"
    assert utility.provenance["source_type"] == "glu_source"


def test_evidence_block_maps_assertions():
    contract = parse(README_GOAL)
    assertions = [item.assertion for item in contract.evidence_requirements]
    assert assertions == [
        "response.status == 200",
        "response.schema valid",
        "services observed",
    ]
    assert contract.evidence_requirements[0].id == "evidence-1"


def test_standalone_limits_block():
    contract = parse(STANDALONE_LIMITS)
    assert contract.id == "parsed-limits"
    assert contract.goals == []
    assert [limit.action_pattern for limit in contract.limits] == [
        "deny *",
        "allow Work.tasks.read",
        "allow Work.tasks.claim",
        "require approval for Deployment.promote",
        "deny Infrastructure.destroy",
    ]


def test_require_approval_for_selector():
    contract = parse("limits {\n    require approval for Deployment.promote\n}")
    assert contract.limits[0].action_pattern == "require approval for Deployment.promote"
    effect, selector = LimitEvaluator.parse_rule(contract.limits[0].action_pattern)
    assert effect == "approval_required"
    assert selector == "Deployment.promote"


def test_deny_dotted_utility_id():
    contract = parse("limits {\n    deny Infrastructure.destroy\n}")
    assert contract.limits[0].action_pattern == "deny Infrastructure.destroy"


def test_prefix_star_selector():
    contract = parse("limits {\n    allow Work.*\n}")
    assert contract.limits[0].action_pattern == "allow Work.*"
    _, selector = LimitEvaluator.parse_rule(contract.limits[0].action_pattern)
    assert selector == "Work.*"


def test_bare_word_selector():
    contract = parse("limits {\n    allow claim\n}")
    assert contract.limits[0].action_pattern == "allow claim"


def test_goal_and_standalone_limits_compose():
    source = README_GOAL + "\n" + STANDALONE_LIMITS
    contract = parse(source)
    assert contract.id == "ServicesHealthy"
    assert len(contract.goals) == 1
    patterns = [limit.action_pattern for limit in contract.limits]
    assert patterns[:2] == ["deny *", "allow Monitoring.services.list"]
    assert patterns[-1] == "deny Infrastructure.destroy"
    assert len(contract.limits) == 7


def test_parse_error_on_empty_source():
    with pytest.raises(ParseError):
        parse("")
