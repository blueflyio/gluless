from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from gluless.evidence import Evidence
from gluless.limits import LimitDecision


@dataclass
class Result:
    run: str
    contract: str
    status: str  # "satisfied" | "blocked" | "waiting_for_approval" | "failed"
    goal: Dict[str, Any]
    invocations: List[Dict[str, Any]] = field(default_factory=list)
    limit_decisions: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    failure: Optional[str] = None
    final_state: Dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, item: str) -> Any:
        if item == "status" and self.status == "satisfied":
            return "success"
        if item == "final_state":
            return self.final_state
        try:
            return getattr(self, item)
        except AttributeError as e:
            raise KeyError(item) from e

class ResultBuilder:
    """
    ResultBuilder constructs the terminal Result representation for a run.
    """
    @staticmethod
    def build(
        run_id: str,
        contract_id: str,
        status: str,
        goal_status: Dict[str, Any],
        invocations: List[Dict[str, Any]],
        limit_decisions: List[LimitDecision],
        evidence: List[Evidence],
        failure: Optional[str] = None,
        final_state: Optional[Dict[str, Any]] = None
    ) -> Result:
        # Convert LimitDecision objects to dictionaries
        limit_dicts = []
        for ld in limit_decisions:
            limit_dicts.append({
                "effect": ld.effect,
                "utility": ld.utility,
                "reason": ld.reason,
                "limit_id": ld.limit_id,
                "constraints": ld.constraints
            })

        return Result(
            run=run_id,
            contract=contract_id,
            status=status,
            goal=goal_status,
            invocations=invocations,
            limit_decisions=limit_dicts,
            evidence=evidence,
            failure=failure,
            final_state=final_state or {}
        )
