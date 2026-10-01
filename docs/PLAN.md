# GluLess — Status & Plan

Product thesis (one place): [README.md](../README.md). This file is the phased plan only.

## Done

| Phase | Slice | Acceptance (observable) |
|-------|--------|-------------------------|
| **0** | Language + IR parser | `parse` / `parse_file` turns `.glu` Goal/Limits into `models.py` IR; pytest green |
| **1** | OpenAPI → Utilities + Limits + HTTP prove | `python -m gluless prove … --mock` prints stage PASSes and can reach `PROVEN=YES` on the Monitoring fixture |
| **2** | Pack + Formula + vertical `ServicesHealthy` | Pack importable; Formula `gluless-prove` `[steps.check]` runs `scripts/gluless-check`; `ServicesHealthy` contract proves under mock; suite green |
| **2.1** | Canonical IR schema | `api/contract.schema.json` generated from `gluless/models.py`; `python -m gluless.schema --check` clean; `api/openapi.yaml` imports → IR → JSON → IR unchanged |

README curation (ship-accurate entry) is also done.

## Next

| Phase | Slice | Acceptance | Status |
|-------|--------|------------|--------|
| **3** | GitLab Goal | A `.glu` Goal against GitLab-shaped Utilities (e.g. merge-request or project read), Limits-enforced, `gluless prove` → `PROVEN=YES` against mock or live OpenAPI projection | **BLOCKED** |

**Blocker (Phase 3):** no GitLab OpenAPI utility projection in-repo (no annotated OpenAPI / importer surface for GitLab operations). Do not paper over with shell/`glab` glue — that violates the product thesis. Unblock when an OpenAPI (or later MCP) Utility surface for the chosen GitLab operations exists and is imported like Monitoring.

## Later (not scheduled until Phase 3 unblocks or explicitly prioritized)

- MCP and A2A Utility adapters
- Approval **resume** after `waiting_for_approval`
- Real response JSON Schema validation (today `response.schema valid` is a coarse heuristic)
- Planner beyond “first READ / first MUTATION”

## Out of scope

- Forking or hacking Gas City
- Declaring GluLess as a Formula or a seventh primitive
- City-local `[[gluless]]` keys
- Manifesto / walkthrough / Scratch plans as product authority (this file + README only)

## Operator proof commands

```bash
python3 -m gluless prove \
  --contract pack/contracts/services-healthy.glu \
  --openapi api/openapi.yaml \
  --mock

./pack/scripts/gluless-check
cd sdk/python && python3 -m pytest
```

Gas City attachment (after pack import): Formula `gluless-prove` check.exec — see [pack/README.md](../pack/README.md).
