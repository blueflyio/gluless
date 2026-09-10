from dataclasses import dataclass, field
from typing import List, Optional

from gluless.models import Contract, SideEffectType, Utility

EFFECT_ALLOW = "allow"
EFFECT_DENY = "deny"
EFFECT_APPROVAL = "approval_required"


@dataclass
class LimitDecision:
    effect: str  # "allow" | "deny" | "approval_required"
    utility: str
    reason: str
    limit_id: Optional[str] = None
    constraints: List[str] = field(default_factory=list)


class LimitEvaluator:
    """
    Evaluate a utility invocation against Contract Limits.

    Rule forms (case-insensitive):
        allow <selector>
        deny <selector>
        require approval for <selector>

    Selector forms:
        *                    everything
        Ns.*                 namespace / prefix glob (Ns, Ns.x, Ns.x.y)
        Ns.res.action        exact utility id
        action               bare word: matches the utility's final id segment,
                             its side-effect class, or its type ("read"/"mutation")

    Arbitrary substring matching is intentionally NOT supported: an authority
    rule must name what it governs. "allow cities" must not match
    "Ns.cities.delete" by accident, and "allow read" must not match
    "Ns.readiness.read".

    Limits are processed in declaration order; the last matching rule wins,
    which supports the canonical "deny *" then "allow X" pattern.

    Secure default when no rule matches:
        READ / NONE side effects  -> allow
        anything else (incl. UNKNOWN) -> deny
    """

    def __init__(self, contract: Contract):
        self.contract = contract

    @staticmethod
    def _matches(selector: str, utility: Utility) -> bool:
        p = selector.lower().strip()
        uid = utility.id.lower()
        if not p:
            return False
        if p == "*":
            return True
        if p.endswith(".*"):
            prefix = p[:-2].rstrip(".")
            return uid == prefix or uid.startswith(prefix + ".")
        if p == uid:
            return True
        if "." not in p:
            if uid.rsplit(".", 1)[-1] == p:
                return True
            if p == utility.side_effects.value or p == utility.type.value:
                return True
        return False

    @staticmethod
    def parse_rule(action_pattern: str):
        """Return (effect, selector) or raise ValueError for an unrecognised rule."""
        rule = action_pattern.strip()
        low = rule.lower()
        if low.startswith("deny "):
            return EFFECT_DENY, rule[5:].strip()
        if low.startswith("allow "):
            return EFFECT_ALLOW, rule[6:].strip()
        if low.startswith("require approval for "):
            return EFFECT_APPROVAL, rule[len("require approval for "):].strip()
        raise ValueError(f"Unrecognised limit rule: '{action_pattern}'")

    def evaluate(self, utility: Utility) -> LimitDecision:
        current_effect = ""
        current_reason = ""
        current_limit_id: Optional[str] = None

        for limit in self.contract.limits:
            effect, selector = self.parse_rule(limit.action_pattern)
            if self._matches(selector, utility):
                current_effect = effect
                current_limit_id = limit.id
                verb = {EFFECT_DENY: "Denied", EFFECT_ALLOW: "Allowed", EFFECT_APPROVAL: "Approval required"}[effect]
                current_reason = f"{verb} by limit '{limit.id}' ({limit.action_pattern})"

        if current_effect:
            return LimitDecision(effect=current_effect, utility=utility.id, reason=current_reason, limit_id=current_limit_id)

        if utility.side_effects in (SideEffectType.NONE, SideEffectType.READ):
            return LimitDecision(
                effect=EFFECT_ALLOW,
                utility=utility.id,
                reason="No limit matched; safe read-only capability permitted by default",
            )
        return LimitDecision(
            effect=EFFECT_DENY,
            utility=utility.id,
            reason=f"No limit matched; mutation/unknown effect '{utility.side_effects.value}' denied by default",
        )
