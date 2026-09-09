"""
tests/test_limits.py
====================

Tests for LimitEvaluator semantics.

The evaluator uses declaration-order, last-match-wins:
  Limits are processed in the order they appear in the contract.
  Each matching rule replaces the current decision.
  The final decision after all rules is returned.

This means "deny *, allow X" → ALLOW  (allow wins because it's last)
and       "allow X, deny *" → DENY   (deny wins because it's last)

The behavior is deliberate: contracts state authorization policy
as an ordered list of rules, not as an unordered set.
"""

import pytest

from gluless.limits import LimitEvaluator
from gluless.models import (
    Contract,
    Goal,
    Limit,
    SideEffectType,
    Utility,
    UtilityTransport,
    UtilityType,
)


# ── Fixtures ──────────────────────────────────────────────────────
def _make_utility(
    utility_id: str,
    side_effects: SideEffectType = SideEffectType.NONE,
    utype: UtilityType = UtilityType.READ,
) -> Utility:
    parts = utility_id.split(".", 1)
    namespace = parts[0]
    name = parts[1] if len(parts) > 1 else utility_id
    return Utility(
        id=utility_id,
        name=name,
        namespace=namespace,
        description="",
        type=utype,
        side_effects=side_effects,
        transport=UtilityTransport(type="openapi", method="GET", path="/test"),
    )


def _make_contract(*limit_patterns: str) -> Contract:
    limits = [
        Limit(id=f"l{i}", action_pattern=pattern)
        for i, pattern in enumerate(limit_patterns)
    ]
    return Contract(
        id="test-contract",
        goals=[Goal(id="g1", expression="x == true")],
        limits=limits,
        utilities=[],
    )


cities_list = _make_utility("GasCity.cities.list", SideEffectType.NONE, UtilityType.READ)
city_create = _make_utility("GasCity.city.create", SideEffectType.CREATE, UtilityType.MUTATION)
city_delete = _make_utility("GasCity.city.delete", SideEffectType.DELETE, UtilityType.MUTATION)
sessions_nudge = _make_utility("GasCity.sessions.nudge", SideEffectType.EXTERNAL_MESSAGE, UtilityType.MUTATION)


# ── Required policy cases ─────────────────────────────────────────

class TestDeclarationOrderLastMatchWins:
    """
    Core semantics: last matching rule wins.

    These four cases are the canonical proof that the evaluator implements
    the intended policy model and not an implementation accident.
    """

    def test_deny_star_then_allow_specific__specific_allowed(self):
        """
        deny *
        allow GasCity.cities.list
        => cities.list ALLOWED  (allow is last and matches)
        """
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(cities_list).effect == "allow"

    def test_deny_star_then_allow_specific__other_still_denied(self):
        """
        deny *
        allow GasCity.cities.list
        => city.create DENIED  (only deny * matched)
        """
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(city_create).effect == "deny"

    def test_allow_star_then_deny_specific__specific_denied(self):
        """
        allow *
        deny GasCity.city.delete
        => city.delete DENIED  (deny is last and matches)
        """
        contract = _make_contract("allow *", "deny GasCity.city.delete")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(city_delete).effect == "deny"

    def test_allow_star_then_deny_specific__other_still_allowed(self):
        """
        allow *
        deny GasCity.city.delete
        => cities.list ALLOWED  (only allow * matched)
        """
        contract = _make_contract("allow *", "deny GasCity.city.delete")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(cities_list).effect == "allow"

    def test_deny_namespace_glob_then_allow_specific__specific_allowed(self):
        """
        deny GasCity.*
        allow GasCity.cities.list
        => cities.list ALLOWED  (allow overrides the namespace deny)
        """
        contract = _make_contract("deny GasCity.*", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(cities_list).effect == "allow"

    def test_deny_namespace_glob_then_allow_specific__other_denied(self):
        """
        deny GasCity.*
        allow GasCity.cities.list
        => city.create DENIED  (namespace deny matched, allow did not)
        """
        contract = _make_contract("deny GasCity.*", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(city_create).effect == "deny"

    def test_allow_specific_then_deny_star__specific_denied(self):
        """
        allow GasCity.cities.list
        deny *
        => cities.list DENIED  (deny * is last and overrides the earlier allow)

        This is the deliberate reversal: order matters.
        If "deny *" appears last, nothing survives.
        """
        contract = _make_contract("allow GasCity.cities.list", "deny *")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(cities_list).effect == "deny"

    def test_allow_specific_then_deny_star__all_denied(self):
        """
        allow GasCity.cities.list
        deny *
        => city.create also DENIED
        """
        contract = _make_contract("allow GasCity.cities.list", "deny *")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(city_create).effect == "deny"


class TestSecureDefaults:
    """
    When no limit matches, the evaluator applies secure defaults.
    """

    def test_no_limits_read_utility__allowed_by_default(self):
        """No limits declared; read-only utility is safe to permit."""
        contract = _make_contract()
        ev = LimitEvaluator(contract)
        result = ev.evaluate(cities_list)
        assert result.effect == "allow"
        assert "default" in result.reason.lower()

    def test_no_limits_mutation_utility__denied_by_default(self):
        """No limits declared; mutation is denied by default."""
        contract = _make_contract()
        ev = LimitEvaluator(contract)
        result = ev.evaluate(city_create)
        assert result.effect == "deny"
        assert "default" in result.reason.lower()

    def test_unmatched_mutation_denied_by_default(self):
        """Limit only allows something else; mutation with no matching rule → denied."""
        contract = _make_contract("allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        result = ev.evaluate(sessions_nudge)
        assert result.effect == "deny"


class TestMatcherRules:
    """
    Verify the _matches logic for each pattern type.
    """

    def test_wildcard_matches_everything(self):
        contract = _make_contract("allow *")
        ev = LimitEvaluator(contract)
        for u in [cities_list, city_create, city_delete, sessions_nudge]:
            assert ev.evaluate(u).effect == "allow", f"Wildcard should allow {u.id}"

    def test_namespace_glob_matches_namespace_only(self):
        """deny GasCity.* should match all GasCity utilities."""
        contract = _make_contract("deny GasCity.*")
        ev = LimitEvaluator(contract)
        for u in [cities_list, city_create, city_delete, sessions_nudge]:
            assert ev.evaluate(u).effect == "deny", f"GasCity.* should deny {u.id}"

    def test_exact_id_match(self):
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        assert ev.evaluate(cities_list).effect == "allow"
        assert ev.evaluate(city_create).effect == "deny"

    def test_side_effect_match(self):
        """Matching on side_effects value 'create' should catch city.create."""
        contract = _make_contract("deny *", "deny create")
        ev = LimitEvaluator(contract)
        result = ev.evaluate(city_create)
        assert result.effect == "deny"

    def test_limit_id_recorded(self):
        """The decision should record which limit_id caused it."""
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        result = ev.evaluate(cities_list)
        assert result.limit_id == "l1"  # second limit (0-indexed: l0=deny, l1=allow)

    def test_deny_limit_id_recorded(self):
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        ev = LimitEvaluator(contract)
        result = ev.evaluate(city_create)
        assert result.limit_id == "l0"  # deny * matched, allow did not


class TestDemoContractSemantics:
    """
    The canonical GluLess demo contract:

        deny *
        allow GasCity.cities.list

    Prove exact runtime behavior for all three registry utilities.
    """

    @pytest.fixture
    def demo_evaluator(self):
        contract = _make_contract("deny *", "allow GasCity.cities.list")
        return LimitEvaluator(contract)

    def test_cities_list_authorized(self, demo_evaluator):
        result = demo_evaluator.evaluate(cities_list)
        assert result.effect == "allow"
        assert "limit-allow-list" not in result.reason  # limit ids are l0/l1 in fixture
        assert "allow GasCity.cities.list" in result.reason

    def test_city_create_denied(self, demo_evaluator):
        result = demo_evaluator.evaluate(city_create)
        assert result.effect == "deny"
        assert "deny *" in result.reason

    def test_sessions_nudge_denied(self, demo_evaluator):
        result = demo_evaluator.evaluate(sessions_nudge)
        assert result.effect == "deny"
        assert "deny *" in result.reason

    def test_city_create_never_executes(self, demo_evaluator):
        """Verify the side_effects of the denied utility (sanity check for UI display)."""
        result = demo_evaluator.evaluate(city_create)
        assert result.effect == "deny"
        assert city_create.side_effects == SideEffectType.CREATE
        assert city_create.type == UtilityType.MUTATION
