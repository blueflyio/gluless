from dataclasses import dataclass, field
from typing import Any, Dict, List

from gluless.experience import ExperienceIndex
from gluless.limits import LimitEvaluator
from gluless.models import Contract, Goal, Limit, Utility
from gluless.registry import UtilityRegistry


@dataclass
class ContextProjection:
    goals: List[Goal]
    limits: List[Limit]
    utilities: List[Utility]
    observations: Dict[str, Any]
    experience: Dict[str, Dict[str, Any]] = field(default_factory=dict)

class ContextResolver:
    """
    ContextResolver dynamically constructs an ephemeral ContextProjection.
    Filters global UtilityRegistry by contract goals and limits,
    ranking capabilities by metrics in the ExperienceIndex.
    """
    def __init__(self, registry: UtilityRegistry, experience_index: ExperienceIndex):
        self.registry = registry
        self.experience_index = experience_index

    def resolve_context(self, contract: Contract, current_observations: Dict[str, Any]) -> ContextProjection:
        # Determine candidate resources by parsing goals
        goal_keywords = []
        for goal in contract.goals:
            expr = goal.expression.lower()
            # extract words/keys like 'cities', 'service', etc.
            goal_keywords.extend([w.strip().split(".")[0] for w in expr.split() if "." in w])

        # 1. Fetch candidates from Registry
        candidates: List[Dict[str, Any]] = []
        for reg_id, ut_data in self.registry.utilities.items():
            # Check if tags or semantic resource domains match the goals keywords
            # or if the operation_id is explicitly allowed/referenced in the contract utilities
            matches_contract = False
            for contract_ut in contract.utilities:
                if contract_ut.id == ut_data["operation_id"]:
                    matches_contract = True
                    break

            if not matches_contract:
                # Check semantic keywords matching
                res_domain = ut_data["semantic_capabilities"].get("domain", "")
                res_resource = ut_data["semantic_capabilities"].get("resource", "")
                if any(kw in reg_id or kw == res_domain or kw == res_resource for kw in goal_keywords):
                    matches_contract = True

            if matches_contract:
                candidates.append(ut_data)

        # 2. Filter candidate utilities against contract Limits (Deterministic Gate)
        # Enforces invariant: PAST_SUCCESS != CURRENT_AUTHORITY
        evaluator = LimitEvaluator(contract)
        allowed_utilities: List[Utility] = []
        experience_metrics: Dict[str, Dict[str, Any]] = {}

        for cand in candidates:
            # Reconstruct model object to evaluate against limits
            reconstructed_utility = self.registry.resolve(cand["utility_id"])
            if not reconstructed_utility:
                continue

            decision = evaluator.evaluate(reconstructed_utility)
            if decision.effect == "allow":
                allowed_utilities.append(reconstructed_utility)
                # Fetch performance metrics from ExperienceIndex
                metrics = self.experience_index.get_metrics(reconstructed_utility.id)
                experience_metrics[reconstructed_utility.id] = metrics

        # 3. Rank allowed utilities based on ExperienceIndex metrics
        # Prioritize high success_rate, then low median_latency.
        # Utilities with 0 executions are placed after high success rate options.
        def rank_key(ut: Utility):
            metrics = experience_metrics[ut.id]
            execs = metrics["executions"]
            suc_rate = metrics["success_rate"]
            med_lat = metrics["median_latency"]
            # If never run, treat success rate as 0.5 for sorting, latency as 9999.0
            if execs == 0:
                return (-0.5, 9999.0)
            return (-suc_rate, med_lat)

        allowed_utilities.sort(key=rank_key)

        return ContextProjection(
            goals=contract.goals,
            limits=contract.limits,
            utilities=allowed_utilities,
            observations=current_observations.copy(),
            experience=experience_metrics
        )
