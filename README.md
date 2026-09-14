# GluLess

**GLU = Goal · Limits · Utilities**

> The contract is the program. Proven done — not glue.

## Concept

A **`.glu` file** is an executable acceptance contract: it names an outcome (**Goal**), the authority that may be used (**Limits**), the capabilities that may satisfy it (**Utilities**), and what counts as proof (**evidence**).

**GluLess** is the language + runtime that parses that contract, authorizes Utilities under Limits, executes them, and evaluates evidence. It exists to stop agent work from decaying into glue scripts, prompt-only “done,” and unverified side effects.

It is **not** a Gas City Formula, not a seventh primitive, and not a `city.toml` key. Gas City already owns Agent / Bead / Formula / Rig / Pack / Event ([docs.gascity.com](https://docs.gascity.com/)). GluLess attaches as:

| Layer | Role |
|-------|------|
| **`.glu` + CLI** | Acceptance contract + `gluless prove` |
| **Pack** (`pack/`) | CONFIGURES — import into a city |
| **Formula** (`gluless-prove`) | HOW — Formula v2 `[steps.check]` runs the CLI |

**Proven Done** means the CLI (or pack check) reports `PROVEN=YES`: parse → authorize → execute → goal evaluation all pass against a real or mock Utility surface, with observable evidence — not a chat claim.

```text
.glu (Goal + Limits + Utilities + evidence)
        │
        ▼
  gluless prove  ──►  RESOLVE → AUTHORIZE → EXECUTE → VERIFY
        │
        ▼
   PROVEN=YES | blocked | waiting_for_approval | failed
```

Language / IR detail: [docs/gluless-specification.md](docs/gluless-specification.md).  
Status and phases: [docs/PLAN.md](docs/PLAN.md).  
Ownership boundary: [OWNERSHIP.md](OWNERSHIP.md).

---

## How it works

### Goal

What must become true — an outcome, not a procedure.

### Limits

What governs execution. Capability availability does not imply permission.

Evaluation is **declaration order, last match wins**. Selectors are exact (no substring matching): `*`, `Work.*`, a full utility id, a bare final segment, a side-effect class, or a utility type.

`require approval for <selector>` stops with `waiting_for_approval`. **Resume after approval is not implemented yet.**

Utilities with side effect `unknown` are denied unless a Limit names them.

### Utilities

Stable capability ids (OpenAPI operations today; MCP / A2A planned). Contracts name ids; the runtime binds transport.

### Example

[`pack/contracts/services-healthy.glu`](pack/contracts/services-healthy.glu):

```glu
goal ServicesHealthy {
    target:
        services.healthy == true

    limits:
        deny *
        allow Monitoring.services.list

    utilities:
        Monitoring.services.list

    evidence:
        response.status == 200
        response.schema valid
        services observed
}
```

### Runtime pipeline

```text
Intent → .glu / IR → Runtime
  RESOLVE   OpenAPI → UtilityRegistry / bind declared ids
  FILTER    Goal-relevant candidates
  AUTHORIZE Limits (last match wins)
  EXECUTE   Permitted Utilities (MVP: HTTP/OpenAPI only)
  VERIFY    Evidence + goal predicate → Result
```

Shipped EXECUTE is HTTP via the OpenAPI importer. MCP and A2A adapters are not shipped.

Result statuses: `satisfied | blocked | waiting_for_approval | failed`.

---

## Status

| Capability | State |
|------------|--------|
| `.glu` parser → `models.py` IR | **Done** (syntax only; no semantic validator) |
| Canonical IR schema (`api/contract.schema.json`, generated from `models.py`) | **Done** |
| OpenAPI Utility importer | **Done** |
| Limits evaluator (last match wins) | **Done** |
| HTTP executor + SHA-256 evidence digests | **Done** |
| CLI `gluless prove` + pack `scripts/gluless-check` | **Done** |
| Pack + Formula `gluless-prove` | **Done** |
| Vertical: `ServicesHealthy` (mock + pytest) | **Done** (Phase 2) |
| GitLab Goal / OpenAPI utility projection | **Blocked** (Phase 3) |

Honest gaps: MCP/A2A adapters, approval resume, real JSON Schema validation for `response.schema valid`, planner beyond first READ/MUTATION.

---

## Plan

See **[docs/PLAN.md](docs/PLAN.md)** for phases, acceptance criteria, and blockers.

Next operator-visible slice: Phase 3 — a GitLab-shaped Goal under Limits — blocked until a GitLab OpenAPI (or equivalent) Utility surface exists to import. Do not invent glue to fake it.

---

## How to run

```bash
cd sdk/python && python3 -m pip install -e '.[dev]'
cd ../..

python3 -m gluless prove \
  --contract pack/contracts/services-healthy.glu \
  --openapi api/openapi.yaml \
  --mock

./pack/scripts/gluless-check
cd sdk/python && python3 -m pytest
```

- Only CLI subcommand today: **`prove`**.
- Parse in code: `from gluless import parse, parse_file`.
- `--mock` / empty `--base-url` → ephemeral all-healthy Monitoring mock.
- Live API: `GLULESS_BASE_URL` / `--base-url`.

Pack check env (argv/env only — never interpolate untrusted formula vars into `sh -c`):

```text
GLULESS_CONTRACT   path to .glu   (default: pack/contracts/services-healthy.glu)
GLULESS_OPENAPI    path to OpenAPI YAML (default: api/openapi.yaml)
GLULESS_BASE_URL   optional API base; unset → ephemeral mock
```

---

## Gas City pack

```text
pack/
  pack.toml
  formulas/gluless-prove.toml   Formula v2 + [steps.check] exec
  contracts/*.glu
  scripts/gluless-check
  examples/validation-city
```

- Import the pack. **Do not** add `[[gluless]]` to `city.toml`.
- **Do not** fork Gas City or invent a seventh primitive.
- Pack CONFIGURES; Formula invokes GluLess at check time.

Operator notes: [`pack/README.md`](pack/README.md).

---

## Non-goals

- Not a Formula language and not a replacement for Gas City orchestration
- Not Cedar / ContractPlane / OPA (Limits bind; they do not replace policy engines)
- Not a general workflow engine, secrets store, or UI framework
- Not “more glue to make agents look done”

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
