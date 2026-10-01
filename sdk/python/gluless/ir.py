"""Canonical serialization and content digest for IR documents.

A Contract's digest is what approvals, evidence and delegated execution bind
to: "approved" means "approved this exact Goal, these Limits, these Utilities".
Two Contracts with the same digest are the same contract.

Canonical form = JSON, keys sorted, no insignificant whitespace, UTF-8,
non-ASCII preserved. This is the same rule `gluless.evidence` uses, so a
contract digest and an evidence digest are comparable artifacts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

from pydantic import BaseModel

from gluless.models import Contract


def canonical_json(node: BaseModel | Dict[str, Any]) -> str:
    data = node.model_dump(mode="json") if isinstance(node, BaseModel) else node
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(node: BaseModel | Dict[str, Any]) -> str:
    """sha256 over the canonical form, prefixed so the algorithm is explicit."""
    return "sha256:" + hashlib.sha256(canonical_json(node).encode("utf-8")).hexdigest()


def contract_id_ref(contract: Contract) -> str:
    """Stable reference to one exact contract: '<id>@<digest>'."""
    return f"{contract.id}@{digest(contract)}"


def load_contract(text: str) -> Contract:
    """Parse a serialized IR document. Unknown keys fail (extra='forbid')."""
    return Contract.model_validate_json(text)


def dump_contract(contract: Contract) -> str:
    return canonical_json(contract)
