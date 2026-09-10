"""Syntax-only `.glu` parser.

Converts Goal, Limits, Utilities, and Evidence blocks into the existing
`models.py` IR. No semantic validation, AST optimization, or Utility
resolution — those belong to later stages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, List, Union

from lark import Lark, Token, Transformer, Tree
from lark.exceptions import LarkError

from gluless.models import (
    Contract,
    EvidenceRequirement,
    Goal,
    Limit,
    SideEffectType,
    Utility,
    UtilityTransport,
    UtilityType,
)

GRAMMAR = r"""
    start: _NL* statement (_NL+ statement)* _NL*

    statement: goal_block | limits_block

    goal_block: "goal" NAME "{" _NL* (goal_section _NL*)* "}"
    goal_section: target_sec | limits_sec | utilities_sec | evidence_sec

    target_sec: "target" ":" _NL+ (REST_LINE _NL+)+
    limits_sec: "limits" ":" _NL+ (limit_stmt _NL+)+
    utilities_sec: "utilities" ":" _NL+ (dotted_ref _NL+)+
    evidence_sec: "evidence" ":" _NL+ (REST_LINE _NL+)+

    limits_block: "limits" "{" _NL* (limit_stmt _NL+)+ "}"

    limit_stmt: deny_stmt | allow_stmt | require_stmt
    deny_stmt: "deny" selector
    allow_stmt: "allow" selector
    require_stmt: "require" "approval" "for" selector

    selector: STAR | prefix_star | dotted_ref
    prefix_star: dotted_ref "." STAR
    dotted_ref: NAME ("." NAME)*

    STAR: "*"
    NAME: /[A-Za-z_][A-Za-z0-9_]*/
    REST_LINE: /[^\n{}:]+/
    _NL: /\r?\n/

    %ignore /[ \t]+/
    %ignore COMMENT
    COMMENT: /#[^\n]*/
"""


class ParseError(Exception):
    """Raised when `.glu` source cannot be parsed into IR."""


def _text(node: Union[str, Token]) -> str:
    return str(node).strip()


def _strings(items: Iterable[Any]) -> List[str]:
    values: List[str] = []
    for item in items:
        if isinstance(item, Token) and item.type == "_NL":
            continue
        if isinstance(item, str):
            text = item.strip()
            if text:
                values.append(text)
        elif isinstance(item, Token):
            text = str(item).strip()
            if text:
                values.append(text)
    return values


def _stub_utility(utility_id: str) -> Utility:
    parts = utility_id.split(".")
    namespace = parts[0] if len(parts) > 1 else ""
    name = ".".join(parts[1:]) if len(parts) > 1 else utility_id
    return Utility(
        id=utility_id,
        name=name,
        namespace=namespace,
        description="",
        type=UtilityType.READ,
        side_effects=SideEffectType.UNKNOWN,
        transport=UtilityTransport(type="unresolved", method="", path=""),
        provenance={"source_type": "glu_source"},
    )


class _GluTransformer(Transformer):
    def dotted_ref(self, parts: List[Token]) -> str:
        return ".".join(_text(part) for part in parts)

    def prefix_star(self, parts: List[Any]) -> str:
        dotted = parts[0]
        return f"{dotted}.*"

    def selector(self, parts: List[Any]) -> str:
        text = _text(parts[0])
        return "*" if text == "*" else text

    def deny_stmt(self, parts: List[str]) -> str:
        return f"deny {parts[0]}"

    def allow_stmt(self, parts: List[str]) -> str:
        return f"allow {parts[0]}"

    def require_stmt(self, parts: List[str]) -> str:
        return f"require approval for {parts[0]}"

    def limit_stmt(self, parts: List[str]) -> str:
        return parts[0]

    def target_sec(self, parts: List[Any]) -> tuple:
        return ("target", _strings(parts))

    def limits_sec(self, parts: List[Any]) -> tuple:
        return ("limits", _strings(parts))

    def utilities_sec(self, parts: List[Any]) -> tuple:
        return ("utilities", _strings(parts))

    def evidence_sec(self, parts: List[Any]) -> tuple:
        return ("evidence", _strings(parts))

    def goal_section(self, parts: List[Any]) -> tuple:
        return parts[0]

    def goal_block(self, parts: List[Any]) -> dict:
        name = ""
        target: List[str] = []
        limits: List[str] = []
        utilities: List[str] = []
        evidence: List[str] = []
        for child in parts:
            if isinstance(child, Token) and child.type == "NAME":
                name = _text(child)
            elif isinstance(child, tuple) and len(child) == 2:
                kind, values = child
                if kind == "target":
                    target.extend(values)
                elif kind == "limits":
                    limits.extend(values)
                elif kind == "utilities":
                    utilities.extend(values)
                elif kind == "evidence":
                    evidence.extend(values)
        return {
            "type": "goal",
            "id": name,
            "target": target,
            "limits": limits,
            "utilities": utilities,
            "evidence": evidence,
        }

    def limits_block(self, parts: List[Any]) -> dict:
        return {"type": "limits", "limits": _strings(parts)}

    def statement(self, parts: List[Any]) -> dict:
        return parts[0]

    def start(self, parts: List[Any]) -> list:
        return [part for part in parts if isinstance(part, dict)]


_PARSER = Lark(GRAMMAR, parser="earley", lexer="dynamic")


def _limits_from_patterns(patterns: List[str], start: int = 1) -> List[Limit]:
    return [
        Limit(id=f"limit-{i}", action_pattern=pattern)
        for i, pattern in enumerate(patterns, start=start)
    ]


def _evidence_from_lines(lines: List[str], start: int = 1) -> List[EvidenceRequirement]:
    return [
        EvidenceRequirement(id=f"evidence-{i}", assertion=line)
        for i, line in enumerate(lines, start=start)
    ]


def _contract_from_statements(statements: List[dict]) -> Contract:
    goals: List[Goal] = []
    limits: List[Limit] = []
    utilities: List[Utility] = []
    evidence: List[EvidenceRequirement] = []
    seen_utility_ids: set[str] = set()

    for stmt in statements:
        if stmt["type"] == "goal":
            expression = "\n".join(stmt["target"]).strip()
            goals.append(Goal(id=stmt["id"], expression=expression))
            limits.extend(_limits_from_patterns(stmt["limits"], start=len(limits) + 1))
            for utility_id in stmt["utilities"]:
                if utility_id not in seen_utility_ids:
                    utilities.append(_stub_utility(utility_id))
                    seen_utility_ids.add(utility_id)
            evidence.extend(_evidence_from_lines(stmt["evidence"], start=len(evidence) + 1))
        elif stmt["type"] == "limits":
            limits.extend(_limits_from_patterns(stmt["limits"], start=len(limits) + 1))

    if not goals and not limits:
        raise ParseError("No Goal or Limits block found")

    contract_id = goals[0].id if goals else "parsed-limits"
    return Contract(
        id=contract_id,
        goals=goals,
        limits=limits,
        utilities=utilities,
        evidence_requirements=evidence,
    )


def parse(source: str) -> Contract:
    """Parse `.glu` source into a `Contract`. Syntax only."""
    try:
        tree = _PARSER.parse(source)
    except LarkError as exc:
        raise ParseError(str(exc)) from exc
    statements = _GluTransformer().transform(tree)
    if isinstance(statements, Tree):
        raise ParseError("Parser did not produce a statement list")
    if not statements:
        raise ParseError("No Goal or Limits block found")
    return _contract_from_statements(statements)


def parse_file(path: str) -> Contract:
    return parse(Path(path).read_text(encoding="utf-8"))
