from typing import List, Optional

import yaml

from gluless.models import Contract, EvidenceRequirement, Goal, Limit, Utility


class CompileError(Exception):
    pass

class GluLessCompiler:
    """
    GluLessCompiler parses structured declarations (YAML/JSON)
    and compiles them into canonical Contract IR models.
    """
    @staticmethod
    def compile_yaml(
        yaml_content: str,
        available_utilities: Optional[List[Utility]] = None
    ) -> Contract:
        """
        Parses YAML content and produces a Contract.
        Validates against available utilities if provided.
        """
        try:
            data = yaml.safe_load(yaml_content)
        except Exception as e:
            raise CompileError(f"Failed to parse YAML content: {e}") from e

        if not isinstance(data, dict):
            raise CompileError("Contract source must be a structured key-value mapping")

        contract_id = data.get("id")
        if not contract_id:
            raise CompileError("Contract 'id' is required")

        # Compile Goals
        goals: List[Goal] = []
        raw_goals = data.get("goals", [])
        if not isinstance(raw_goals, list):
            raise CompileError("'goals' must be a list of goal declarations")

        for idx, g in enumerate(raw_goals):
            if not isinstance(g, dict):
                raise CompileError(f"Goal at index {idx} must be a dictionary")
            goal_id = g.get("id")
            expr = g.get("expression")
            if not goal_id or not expr:
                raise CompileError(f"Goal at index {idx} is missing required fields ('id', 'expression')")
            goals.append(Goal(
                id=goal_id,
                expression=expr,
                description=g.get("description"),
                version=str(g.get("version", "1.0.0"))
            ))

        # Compile Limits
        limits: List[Limit] = []
        raw_limits = data.get("limits", [])
        if not isinstance(raw_limits, list):
            raise CompileError("'limits' must be a list of limit declarations")

        for idx, lim in enumerate(raw_limits):
            if not isinstance(lim, dict):
                raise CompileError(f"Limit at index {idx} must be a dictionary")
            limit_id = lim.get("id")
            pattern = lim.get("action_pattern")
            if not limit_id or not pattern:
                raise CompileError(f"Limit at index {idx} is missing required fields ('id', 'action_pattern')")
            limits.append(Limit(
                id=limit_id,
                action_pattern=pattern,
                description=lim.get("description"),
                version=str(lim.get("version", "1.0.0"))
            ))

        # Compile Evidence Requirements
        evidence_reqs: List[EvidenceRequirement] = []
        raw_evidence = data.get("evidence_requirements", [])
        if not isinstance(raw_evidence, list):
            raise CompileError("'evidence_requirements' must be a list of evidence declarations")

        for idx, ev in enumerate(raw_evidence):
            if not isinstance(ev, dict):
                raise CompileError(f"EvidenceRequirement at index {idx} must be a dictionary")
            ev_id = ev.get("id")
            assertion = ev.get("assertion")
            if not ev_id or not assertion:
                raise CompileError(f"EvidenceRequirement at index {idx} is missing required fields ('id', 'assertion')")
            evidence_reqs.append(EvidenceRequirement(
                id=ev_id,
                assertion=assertion,
                description=ev.get("description"),
                version=str(ev.get("version", "1.0.0"))
            ))

        # Compile Utilities (References to available utilities or inline declarations)
        utilities: List[Utility] = []
        raw_utilities = data.get("utilities", [])
        if not isinstance(raw_utilities, list):
            raise CompileError("'utilities' must be a list of utility declarations")

        # Map available utilities by ID for quick lookup
        util_map = {u.id: u for u in available_utilities} if available_utilities else {}

        for idx, u_ref in enumerate(raw_utilities):
            if isinstance(u_ref, str):
                # Referenced utility: must exist in available_utilities
                if u_ref not in util_map:
                    raise CompileError(f"Referenced utility '{u_ref}' at index {idx} could not be resolved")
                utilities.append(util_map[u_ref])
            elif isinstance(u_ref, dict):
                # Inline utility definition or selector mapping
                ref_id = u_ref.get("id")
                if ref_id and ref_id in util_map:
                    utilities.append(util_map[ref_id])
                else:
                    raise CompileError(f"Utility definition/reference at index {idx} is invalid or unresolved")
            else:
                raise CompileError(f"Invalid utility reference format at index {idx}")

        return Contract(
            id=contract_id,
            goals=goals,
            limits=limits,
            utilities=utilities,
            evidence_requirements=evidence_reqs
        )
