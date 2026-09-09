import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Evidence:
    id: str
    kind: str  # "state_observation" | "mutation_action"
    claim: Dict[str, Any]
    source: Dict[str, Any]
    observed_at: str
    digest: str
    provenance: Dict[str, str]

class EvidenceBuilder:
    """
    Builds content-addressed Evidence: a SHA-256 digest over the canonical
    (key-sorted) serialization of kind/claim/source/provenance. This is an
    integrity digest, not a signature; signing belongs to an external
    EvidenceStore.
    """
    @staticmethod
    def build(
        kind: str,
        claim: Dict[str, Any],
        source_utility: str,
        run_id: str,
        contract_id: str,
        observed_at: Optional[str] = None
    ) -> Evidence:
        if not observed_at:
            observed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        source = {"utility": source_utility}
        provenance = {
            "run": run_id,
            "contract": contract_id
        }

        # Create canonical dict for digest calculation
        canonical_data = {
            "kind": kind,
            "claim": claim,
            "source": source,
            "provenance": provenance
        }

        # Deterministic sorting and serialization
        serialized = json.dumps(canonical_data, sort_keys=True)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

        evidence_id = f"evidence:{digest[:16]}"

        return Evidence(
            id=evidence_id,
            kind=kind,
            claim=claim,
            source=source,
            observed_at=observed_at,
            digest=digest,
            provenance=provenance
        )
