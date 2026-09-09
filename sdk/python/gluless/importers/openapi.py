"""OpenAPI -> Utility importer.

Identity rules (deterministic, collision-free by construction):

    namespace  = x-provider-name | slug(info.title) | default_namespace
    resource   = every non-parameter path segment after version/api prefixes,
                 joined with "." (for /city/{n}/session/{id}/kill -> "city.session")
    action     = GET  -> "list" (collection) | "read" (ends in a parameter slot)
                 POST -> last word segment when it follows a parameter slot
                         (an RPC-style action such as .../{id}/kill), else "create"
                 PUT/PATCH -> "update", DELETE -> "delete", other -> method
    id         = f"{namespace}.{resource}.{action}"

`x-gluless-name` overrides the derived identity. Duplicate ids are an import
error: Limits target ids, so two operations sharing one id would share one
authority decision.

Side effects (declared): GET -> READ, PUT/PATCH -> UPDATE, DELETE -> DELETE,
POST create -> CREATE, POST RPC action -> UNKNOWN. UNKNOWN is deliberate: an
action like `kill` must not inherit the authority of `create`.
`x-gluless-side-effects` overrides.
"""
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from gluless.models import SideEffectType, Utility, UtilityTransport, UtilityType

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_PREFIX_PATTERNS = (r"^v[0-9]+$", r"^api$", r"^v[0-9]+\.[0-9]+$")


class UtilityImportError(ValueError):
    """Raised when an OpenAPI document cannot be projected into a valid Utility set."""


def _unescape_pointer(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def resolve_ref(ref_str: str, document: Dict[str, Any]) -> Any:
    if not ref_str.startswith("#/"):
        return {"$ref": ref_str}
    curr: Any = document
    for raw in ref_str[2:].split("/"):
        part = _unescape_pointer(raw)
        if isinstance(curr, dict) and part in curr:
            curr = curr[part]
        elif isinstance(curr, list):
            try:
                curr = curr[int(part)]
            except (ValueError, IndexError):
                return {"$ref": ref_str}
        else:
            return {"$ref": ref_str}
    return curr


def resolve_all_refs(node: Any, document: Dict[str, Any], resolved_paths: Optional[set] = None) -> Any:
    if resolved_paths is None:
        resolved_paths = set()
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref in resolved_paths:
                return {"$ref": ref}  # cycle: leave the reference in place
            resolved_paths.add(ref)
            return resolve_all_refs(resolve_ref(ref, document), document, resolved_paths)
        return {k: resolve_all_refs(v, document, resolved_paths.copy()) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_all_refs(item, document, resolved_paths.copy()) for item in node]
    return node


def _is_param(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def derive_utility_name(
    method: str,
    path: str,
    operation_id: Optional[str] = None,
    sibling_methods: Tuple[str, ...] = (),
) -> Tuple[str, str]:
    """Return (resource, action).

    operation_id is accepted for API compatibility and recorded as provenance by
    the importer; it does not influence identity. sibling_methods lists the other
    HTTP methods on the same path: a POST on a path that also serves GET is a
    collection create (`/city/{c}/sessions`), a POST-only path ending in a word
    after a parameter is an RPC action (`/session/{id}/kill`)."""
    segments = [s for s in path.strip("/").split("/") if s]
    while segments and any(re.match(p, segments[0], re.IGNORECASE) for p in _PREFIX_PATTERNS):
        segments.pop(0)
    if not segments:
        return ("root", method.lower())

    words = [s for s in segments if not _is_param(s)]
    if not words:
        raise UtilityImportError(
            f"Cannot derive a resource name for {method.upper()} {path}: "
            "path has no literal segments; declare x-gluless-name"
        )

    m = method.upper()
    ends_in_param = _is_param(segments[-1])
    rpc_action = (
        m == "POST"
        and not ends_in_param
        and len(segments) >= 2
        and _is_param(segments[-2])
        and "get" not in {x.lower() for x in sibling_methods}
    )

    if rpc_action:
        return (".".join(words[:-1]), words[-1])
    resource = ".".join(words)
    if m == "GET":
        return (resource, "read" if ends_in_param else "list")
    if m == "POST":
        return (resource, "create")
    if m in ("PUT", "PATCH"):
        return (resource, "update")
    if m == "DELETE":
        return (resource, "delete")
    return (resource, m.lower())


def _declared_side_effects(method: str, action: str) -> Tuple[SideEffectType, UtilityType]:
    m = method.upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return SideEffectType.READ, UtilityType.READ
    if m == "POST":
        if action == "create":
            return SideEffectType.CREATE, UtilityType.MUTATION
        return SideEffectType.UNKNOWN, UtilityType.MUTATION
    if m in ("PUT", "PATCH"):
        return SideEffectType.UPDATE, UtilityType.MUTATION
    if m == "DELETE":
        return SideEffectType.DELETE, UtilityType.MUTATION
    return SideEffectType.UNKNOWN, UtilityType.MUTATION


def _merge_parameters(path_params: List[Any], op_params: List[Any]) -> List[Dict[str, Any]]:
    """Operation-level parameters override path-level ones with the same (name, in)."""
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in list(path_params) + list(op_params):
        if isinstance(p, dict) and "name" in p:
            merged[(p["name"], p.get("in", ""))] = p
    return list(merged.values())


def _json_schema(container: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(container, dict):
        return None
    content = container.get("content")
    if not isinstance(content, dict) or not content:
        return None
    media = content.get("application/json")
    if media is None:
        # first media type wins; the media type is recorded alongside the schema
        media = next(iter(content.values()))
    if isinstance(media, dict):
        return media.get("schema")
    return None


class OpenAPIImporter:
    def __init__(self, default_namespace: str = "Default"):
        self.default_namespace = default_namespace
        self.diagnostics: List[str] = []

    def import_spec(self, spec_content: str, source_uri: Optional[str] = None) -> List[Utility]:
        self.diagnostics = []
        document = yaml.safe_load(spec_content)
        if not isinstance(document, dict) or "paths" not in document:
            raise UtilityImportError("Invalid OpenAPI document structure: expected a mapping with 'paths'")

        info = document.get("info") if isinstance(document.get("info"), dict) else {}
        namespace = document.get("x-provider-name") or (
            re.sub(r"[^a-zA-Z0-9]", "", str(info["title"])) if info.get("title") else self.default_namespace
        )
        doc_version = str(info.get("version", "0.0.0"))
        doc_digest = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()
        doc_servers = [s.get("url") for s in document.get("servers", []) if isinstance(s, dict) and s.get("url")]
        doc_security = document.get("security")  # None means "not declared"; [] means "explicitly none"
        if "webhooks" in document:
            self.diagnostics.append("webhooks are not imported")

        utilities: List[Utility] = []
        seen: Dict[str, str] = {}

        for path, path_item in (document.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            if "$ref" in path_item:
                self.diagnostics.append(f"path-level $ref not supported, skipped: {path}")
                continue
            path_params = resolve_all_refs(path_item.get("parameters", []), document)
            path_servers = [s.get("url") for s in path_item.get("servers", []) if isinstance(s, dict)]

            for method, operation in path_item.items():
                if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                op = resolve_all_refs(operation, document)
                if op.get("x-gluless-exclude") is True:
                    continue

                siblings = tuple(k for k in path_item if k.lower() in HTTP_METHODS and k != method)
                resource, action = derive_utility_name(method, path, op.get("operationId"), siblings)
                ns = namespace
                custom_name = op.get("x-gluless-name")
                if custom_name:
                    parts = str(custom_name).split(".")
                    if len(parts) >= 3:
                        ns, resource, action = parts[0], parts[1], ".".join(parts[2:])
                    elif len(parts) == 2:
                        resource, action = parts
                    else:
                        action = parts[0]

                utility_id = f"{ns}.{resource}.{action}"
                location = f"{method.upper()} {path}"
                if utility_id in seen:
                    raise UtilityImportError(
                        f"Duplicate utility id '{utility_id}' for {location} (already used by {seen[utility_id]}); "
                        "declare x-gluless-name on one of them"
                    )
                seen[utility_id] = location

                side_effects, utility_type = _declared_side_effects(method, action)
                if op.get("x-gluless-type"):
                    try:
                        utility_type = UtilityType(str(op["x-gluless-type"]).lower())
                    except ValueError as e:
                        raise UtilityImportError(f"{location}: invalid x-gluless-type '{op['x-gluless-type']}'") from e
                if op.get("x-gluless-side-effects"):
                    try:
                        side_effects = SideEffectType(str(op["x-gluless-side-effects"]).lower())
                    except ValueError as e:
                        raise UtilityImportError(
                            f"{location}: invalid x-gluless-side-effects '{op['x-gluless-side-effects']}'"
                        ) from e

                responses: Dict[str, Optional[Dict[str, Any]]] = {}
                for status, resp in (op.get("responses") or {}).items():
                    responses[str(status)] = _json_schema(resp) if isinstance(resp, dict) else None

                op_servers = [s.get("url") for s in op.get("servers", []) if isinstance(s, dict)]
                security = op["security"] if "security" in op else doc_security
                if security is None:
                    security = []

                transport = UtilityTransport(
                    type="openapi",
                    method=method.upper(),
                    path=path,
                    parameters=_merge_parameters(path_params, op.get("parameters", [])),
                    request_body=_json_schema(op.get("requestBody")),
                    responses=responses,
                    servers=op_servers or path_servers or doc_servers,
                    deprecated=bool(op.get("deprecated", False)),
                )
                utilities.append(
                    Utility(
                        id=utility_id,
                        name=f"{resource}.{action}",
                        namespace=ns,
                        description=op.get("summary") or op.get("description") or "",
                        type=utility_type,
                        side_effects=side_effects,
                        transport=transport,
                        auth=security,
                        version=doc_version,
                        provenance={
                            "source_type": "openapi",
                            "source_uri": source_uri or "",
                            "source_version": doc_version,
                            "source_digest": doc_digest,
                            "operation_id": op.get("operationId") or "",
                            "location": location,
                        },
                    )
                )
        return utilities
