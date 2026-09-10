"""Authority selectors must name what they govern."""
import pytest

from gluless.limits import EFFECT_APPROVAL, LimitEvaluator
from gluless.models import Contract, Limit, SideEffectType, Utility, UtilityTransport, UtilityType


def _u(uid: str, effects=SideEffectType.CREATE, utype=UtilityType.MUTATION) -> Utility:
    ns, rest = uid.split(".", 1)
    return Utility(id=uid, name=rest, namespace=ns, description="", type=utype, side_effects=effects,
                   transport=UtilityTransport(type="openapi", method="POST", path="/x"))


def _ev(*rules: str) -> LimitEvaluator:
    return LimitEvaluator(Contract(id="c", goals=[], limits=[Limit(id=f"l{i}", action_pattern=r) for i, r in enumerate(rules)], utilities=[]))


def test_no_substring_matching():
    # "allow cities" must not grant cities.delete; "allow read" must not match readiness
    assert _ev("deny *", "allow cities").evaluate(_u("Ns.cities.delete", SideEffectType.DELETE)).effect == "deny"
    assert _ev("deny *", "allow ness").evaluate(_u("Ns.readiness.list", SideEffectType.READ, UtilityType.READ)).effect == "deny"
    assert _ev("deny *", "allow sessions").evaluate(_u("Ns.sessions.kill", SideEffectType.UNKNOWN)).effect == "deny"


def test_bare_word_matches_final_action_segment():
    assert _ev("deny *", "allow nudge").evaluate(_u("Ns.sessions.nudge", SideEffectType.UNKNOWN)).effect == "allow"
    assert _ev("deny *", "allow nudge").evaluate(_u("Ns.sessions.kill", SideEffectType.UNKNOWN)).effect == "deny"


def test_bare_word_matches_side_effect_class():
    assert _ev("allow *", "deny delete").evaluate(_u("Ns.things.remove", SideEffectType.DELETE)).effect == "deny"


def test_require_approval():
    d = _ev("deny *", "require approval for Ns.prod.deploy").evaluate(_u("Ns.prod.deploy", SideEffectType.INFRASTRUCTURE))
    assert d.effect == EFFECT_APPROVAL
    assert d.limit_id == "l1"


def test_unknown_rule_is_rejected():
    with pytest.raises(ValueError):
        _ev("permit *").evaluate(_u("Ns.a.b"))


def test_unknown_side_effect_denied_by_default():
    assert _ev().evaluate(_u("Ns.session.kill", SideEffectType.UNKNOWN)).effect == "deny"
