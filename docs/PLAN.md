# GluLess — Status & Plan

**Role: REFERENCE_ONLY.** Architecture and ship-status narrative. **Not** the execution system of record.

Work state (open / blocked / ready / claim / close) lives in **canonical City/HQ Beads** — Oracle `city_canonical` `127.0.0.1:3308` / database `hq` / prefix `hq` (city-scoped `hq-*` for this POC; GluLess is not a `city.toml` rig). Prefer `blu work` → Oracle, or `bd` from Oracle `~/gt`. Do not create a local GluLess Dolt or treat Mac BluCity `:38991` / `bc` as authority.

Product thesis (one place): [README.md](../README.md). This file is the phased plan only.

## Done

| Phase | Slice | Acceptance (observable) |
|-------|--------|-------------------------|
| **0** | Language + IR parser | `parse` / `parse_file` turns `.glu` Goal/Limits into `models.py` IR; pytest green |
| **1** | OpenAPI → Utilities + Limits + HTTP prove | `python -m gluless prove … --mock` prints stage PASSes and can reach `PROVEN=YES` on the Monitoring fixture |
| **2** | Pack + Formula + vertical `ServicesHealthy` | Pack importable; Formula `gluless-prove` `[steps.check]` runs `scripts/gluless-check`; `ServicesHealthy` contract proves under mock; suite green |

README curation (ship-accurate entry) is also done.

## Next

| Phase | Slice | Acceptance | Status |
|-------|--------|------------|--------|
| **3** | GitLab Goal | A `.glu` Goal against GitLab-shaped Utilities (e.g. merge-request or project read), Limits-enforced, `gluless prove` → `PROVEN=YES` against mock or live OpenAPI projection | **BLOCKED** (ledger: city `hq-*` Beads) |

**Blocker (Phase 3):** no GitLab OpenAPI utility projection importable like Monitoring (annotated OpenAPI → Utilities). Do not paper over with shell/`glab` glue — that violates the product thesis. Track Phase 3 + the OpenAPI utility-projection dependency as city-scoped `hq-*` Beads (labels/project `gluless`); this file only mirrors status.

Likely dependency owner (investigate before assigning): `api-schema-registry` (platform OpenAPI corpus) and/or Drupal `api_normalization` service-plane projections — not GluLess itself. `gitlab_components` is CI, not the OpenAPI utility surface.

## Later (deferred Beads / backlog — not in_progress)

- MCP and A2A Utility adapters
- Approval **resume** after `waiting_for_approval`
- Real response JSON Schema validation (today `response.schema valid` is a coarse heuristic)
- Canonical published IR schema (beyond Python dataclasses)
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
