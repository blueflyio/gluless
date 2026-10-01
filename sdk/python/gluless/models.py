"""Canonical GluLess intermediate representation.

This module is the SINGLE hand-authored definition of the IR. Everything else
is derived from it:

    models.py  (Pydantic v2, authored)
        -> api/contract.schema.json  (JSON Schema, generated, drift-gated by
           tests/test_ir_schema.py)

Do not hand-edit `api/contract.schema.json`. Regenerate it with:

    python -m gluless.schema --write

Pydantic was selected because it is already a REQUIRED transitive dependency
(`ag-ui-protocol` requires it) and because it both validates instances and
emits JSON Schema, so one definition serves the Python runtime and the
language-neutral contract the Go/TypeScript SDKs will need.

`extra="forbid"` is deliberate: an unknown key in a serialized IR document is
an error, not a silently dropped field. The IR carries authority decisions; it
must fail closed the way the Limit evaluator does.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

#: Version of the IR *schema* — not of any contract expressed in it.
IR_VERSION = "0.1.0"

SCHEMA_ID = "https://gluless.dev/schema/contract-0.1.0.json"


class SideEffectType(str, Enum):
    """Declared side-effect class of a Utility. Never inferred from behaviour."""

    NONE = "none"
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXTERNAL_MESSAGE = "external_message"
    FINANCIAL = "financial"
    PRIVILEGE_CHANGE = "privilege_change"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class UtilityType(str, Enum):
    """Execution class of a Utility: how the runtime may use it."""

    READ = "read"
    MUTATION = "mutation"
    STREAM = "stream"


class IRModel(BaseModel):
    """Base for every IR node: strict, no undeclared keys."""

    model_config = ConfigDict(extra="forbid")


class UtilityTransport(IRModel):
    """How a Utility is actually invoked. Populated by an importer, consumed by
    `gluless.bindings.UtilityResolver`."""

    type: str = Field(description="Transport family, e.g. 'openapi', or 'unresolved' for a parser stub.")
    method: str = Field(description="HTTP method, upper-case. Empty for an unresolved stub.")
    path: str = Field(description="Templated request path, e.g. '/city/{name}/sessions'.")
    parameters: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="OpenAPI Parameter Objects, $ref-resolved. Operation-level entries override path-level ones.",
    )
    request_body: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON Schema of the request body, or null when the operation declares none.",
    )
    responses: Dict[str, Any] = Field(
        default_factory=dict,
        description="Status code (as a string) -> response JSON Schema, or null when none is declared.",
    )
    servers: List[str] = Field(
        default_factory=list,
        description="Base URLs from the source document, most specific level first (operation, path, document).",
    )
    deprecated: bool = Field(default=False, description="Mirrors the source document's `deprecated` flag.")


class Utility(IRModel):
    """A named, authority-bearing capability. `id` is what a Limit selector targets,
    so it must be unique within a contract; importers fail closed on duplicates."""

    id: str = Field(description="Fully qualified identity: '<namespace>.<resource>.<action>'.")
    name: str = Field(description="Identity without the namespace: '<resource>.<action>'.")
    namespace: str = Field(description="Provider namespace, e.g. 'GasCity'.")
    description: str = Field(description="Human-readable summary. Never used for authority.")
    type: UtilityType
    side_effects: SideEffectType
    transport: UtilityTransport
    auth: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="OpenAPI Security Requirement Objects. An empty list means 'explicitly none'.",
    )
    version: str = Field(default="0.0.0", description="Version of the source document this was imported from.")
    provenance: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Where this Utility came from: source_type, source_uri, source_version, "
            "source_digest, operation_id, location. Never used for authority."
        ),
    )


class Goal(IRModel):
    """An outcome that must become true for a run to be satisfied."""

    id: str
    expression: str = Field(
        description="Goal expression. The runtime currently evaluates '<dotted.path> == <value>' and '!='."
    )
    description: Optional[str] = None
    version: str = "1.0.0"


class Limit(IRModel):
    """An authority rule. Evaluated in declaration order; the last match wins."""

    id: str
    action_pattern: str = Field(
        description="'allow <selector>' | 'deny <selector>' | 'require approval for <selector>'."
    )
    description: Optional[str] = None
    version: str = "1.0.0"


class EvidenceRequirement(IRModel):
    """An assertion that must hold over observed state for a run to be provable."""

    id: str
    assertion: str
    description: Optional[str] = None
    version: str = "1.0.0"


class Contract(IRModel):
    """The root IR document. Produced by the `.glu` parser, the YAML compiler, or
    assembled from imported Utilities; consumed by the runtime and the resolver."""

    id: str
    goals: List[Goal]
    limits: List[Limit]
    utilities: List[Utility]
    evidence_requirements: List[EvidenceRequirement] = Field(default_factory=list)
    ir_version: str = Field(
        default=IR_VERSION,
        description="Version of the IR schema this document conforms to.",
    )
