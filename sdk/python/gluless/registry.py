import json
import os
from typing import Any, Dict, List, Optional

from gluless.models import SideEffectType, Utility


class UtilityRegistry:
    """
    UtilityRegistry is a persistent knowledge plane for canonical Utility definitions.
    Caches capability descriptions from OpenAPI, GraphQL, MCP, etc.

    Pass registry_path=":memory:" for a transient per-process registry that never
    touches disk. The default persists to ~/.gluless/utility_registry.json.
    """
    def __init__(self, registry_path: Optional[str] = None):
        if registry_path == ":memory:":
            self.registry_path = ":memory:"
            self._in_memory = True
        elif not registry_path:
            self.registry_path = os.path.join(
                os.environ.get("GLULESS_HOME", os.path.expanduser("~/.gluless")), "utility_registry.json"
            )
            self._in_memory = False
        else:
            self.registry_path = registry_path
            self._in_memory = False

        if not self._in_memory:
            self._ensure_dir()
        self.utilities: Dict[str, Dict[str, Any]] = self._load()

    def _ensure_dir(self):
        dir_name = os.path.dirname(self.registry_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._in_memory:
            return {}
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self):
        if self._in_memory:
            return  # no-op for in-memory registry
        self._ensure_dir()
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self.utilities, f, indent=2)


    def register(
        self,
        utility: Utility,
        source_uri: str,
        source_digest: str,
        source_version: str = "0.1.0",
        semantic_capabilities: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Registers a utility into the master registry.
        Constructs a unique URI scheme identity: utility://{namespace}/{name}
        """
        registry_id = f"utility://{utility.namespace.lower()}/{utility.name.lower()}"

        # Preserve declared vs observed side effects
        side_effect_data = {
            "declared": utility.side_effects.value,
            "observed": "unknown",
            "confidence": 0.0,
            "samples": 0
        }

        # The canonical IR, serialized by the schema that defines it. Every other
        # key below is a derived search index over this record; `utility` is the
        # only field `resolve()` reads back, so the round-trip cannot drift.
        canonical = utility.model_dump(mode="json")

        self.utilities[registry_id] = {
            "utility": canonical,
            "utility_id": registry_id,
            "source_type": utility.transport.type,
            "source_uri": source_uri,
            "source_digest": source_digest,
            "source_version": source_version,
            "operation_id": utility.id,
            "input_schema": utility.transport.request_body or {},
            "output_schema": utility.transport.responses or {},
            "side_effect": side_effect_data,
            "auth_requirements": utility.auth,
            "errors": [],
            "tags": [utility.namespace.lower(), utility.name.split(".")[-1]],
            "semantic_capabilities": semantic_capabilities or {
                "domain": utility.namespace.lower(),
                "resource": utility.name.split(".")[0].lower()
            },
            "provenance": dict(utility.provenance, source_uri=source_uri),
            "version": utility.version,
            "transport": canonical["transport"],
            "type": utility.type.value
        }
        self.save()
        return registry_id

    def update_observation(self, registry_id: str, observed_effect: str, confidence: float):
        """
        Enriches declarative utility metadata with observed empirical behavior.
        Preserves canonical invariant: DECLARED_SEMANTICS != OBSERVED_BEHAVIOR
        """
        if registry_id in self.utilities:
            se = self.utilities[registry_id]["side_effect"]
            se["observed"] = observed_effect
            se["confidence"] = confidence
            se["samples"] += 1
            self.save()

    def search(self, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search utilities matching filter criteria (e.g. domain, input parameters, max side-effect limit).
        """
        results = []
        for ut in self.utilities.values():
            match = True

            # Filter by domain / resource
            if "domain" in criteria:
                if ut["semantic_capabilities"].get("domain") != criteria["domain"].lower():
                    match = False

            # Filter by side effects (e.g. read-only checks)
            if "max_effect" in criteria:
                declared_effect = ut["side_effect"]["declared"]
                if criteria["max_effect"] == "read":
                    if declared_effect not in (SideEffectType.NONE.value, SideEffectType.READ.value):
                        match = False

            # Filter by inputs
            if "requires_input" in criteria:
                required = criteria["requires_input"]
                params = ut["transport"].get("parameters", [])
                param_names = [p["name"] for p in params]
                if required not in param_names:
                    match = False

            if match:
                results.append(ut)

        return results

    def resolve(self, utility_id: str) -> Optional[Utility]:
        """Deserialize a registered record back into the Utility IR.

        Reads only the canonical `utility` payload written by `register()`, so
        this is the exact inverse of serialization. A record written before the
        canonical IR existed is treated as an unresolvable stale cache entry —
        the registry is a regenerable index, not an authority.
        """
        ut = self.utilities.get(utility_id)
        if not ut or not isinstance(ut.get("utility"), dict):
            return None
        return Utility.model_validate(ut["utility"])
