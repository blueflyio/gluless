# GluLess

**An agent-native executable contract language and runtime.**

**GLU = Goal · Limits · Utilities**

> **The contract is the program.**

GluLess lets humans and agents declare an outcome (**Goal**), the authority that governs it (**Limits**), and the capabilities available to reach it (**Utilities**). The runtime resolves, authorizes, executes, and verifies — without hand-written integration glue.

GluLess is **not** a Gas City Formula, not a seventh primitive, and not a city config key. The product story is **proven done**: a Goal is satisfied under Limits via typed Utilities, with evidence.

| Layer | Role |
|-------|------|
| **GluLess** | Executable acceptance contract (`.glu` / IR) |
| **Pack** (`pack/`) | CONFIGURES — import into a city |
| **Formula** (`gluless-prove`) | HOW — Formula v2 `[steps.check]` invokes the GluLess CLI |

Further reading: [llms.txt](llms.txt), [OWNERSHIP.md](OWNERSHIP.md), [docs/gluless-specification.md](docs/gluless-specification.md).

---

## GLU

### Goal

What must become true — an outcome, not a procedure.

### Limits

What governs execution. Capability availability does not imply permission.

Evaluation is **declaration order, last match wins**. Selectors are exact (no substring matching): `*`, `Work.*`, a full utility id, a bare final segment, a side-effect class, or a utility type.

`require approval for <selector>` stops the run with status `waiting_for_approval`. **Resume after approval is not implemented yet.**

Utilities with side effect `unknown` (for example an RPC-style POST without `x-gluless-side-effects`) are denied unless a Limit names them. Unknown never inherits the authority of `create`.

### Utilities

Stable capabilities (OpenAPI operations today; MCP tools and A2A agents planned). Contracts name utility ids; the runtime binds transport.

### Example (repo contract)

From [`pack/contracts/services-healthy.glu`](pack/contracts/services-healthy.glu):

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

Standalone Limits block (supported by the parser):

```glu
limits {
    deny *
    allow Work.tasks.read
    allow Work.tasks.claim
    require approval for Deployment.promote
    deny Infrastructure.destroy
}
```

---

## Architecture

```text
Intent
  → Goal + Limits + Utilities  (.glu or structured IR)
  → Typed models.py IR
  → Runtime
       RESOLVE   OpenAPI → UtilityRegistry / bind declared ids
       FILTER    Goal-relevant candidates (capability domain)
       AUTHORIZE Limits (declaration order, last match wins)
       EXECUTE   Invoke permitted Utilities (MVP: HTTP/OpenAPI only)
       VERIFY    Evidence + goal predicate → Result
```

**Shipped MVP EXECUTE** is HTTP via the OpenAPI importer and `UtilityResolver`. MCP and A2A adapters are not shipped.

Runtime `Result.status` values:

```text
satisfied | blocked | waiting_for_approval | failed
```

The CLI prove path prints stage lines such as `PARSE=PASS`, `AUTHORIZE=PASS`, `HTTP_EXECUTION=PASS`, `GOAL_EVALUATION=PASS`, and `PROVEN=YES` when the Goal is satisfied under Limits against a live or mock API.

OpenAPI is the first Utility adapter. Per-operation `x-gluless-name` / `x-gluless-type` / `x-gluless-side-effects` declare GluLess identity on the API contract; the importer projects them into the registry.

---

## Status

| Capability | State |
|------------|--------|
| `.glu` parser (`sdk/python/gluless/parser.py`) | **Shipped** — syntax → `models.py` IR; no semantic validation |
| OpenAPI Utility importer | **Shipped** |
| Limits evaluator (last match wins) | **Shipped** |
| HTTP executor + evidence digests (SHA-256) | **Shipped** |
| CLI `gluless prove` + pack `scripts/gluless-check` | **Shipped** |
| MVP vertical slice (mock + tests) | **Works** |

Proven under test: OpenAPI → typed Utilities; Goals/Limits govern execution; runs are observable (limits, utilities, evidence).

---

## How to run

From the repository root (after a checkout of this tree):

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

- Entry point: `gluless` → `gluless.cli:main` (also `python3 -m gluless`).
- Only CLI subcommand today: **`prove`**. There is no separate `parse` command.
- Parse programmatically: `from gluless import parse, parse_file`.
- `--mock` (or empty `--base-url`) starts an **ephemeral** all-healthy Monitoring mock for the prove path.
- Optional live API: set `GLULESS_BASE_URL` / `--base-url` (include the version prefix your OpenAPI expects).

Env vars used by the pack check script (argv/env only — never interpolate untrusted formula vars into `sh -c`):

```text
GLULESS_CONTRACT   path to .glu   (default: pack/contracts/services-healthy.glu)
GLULESS_OPENAPI    path to OpenAPI YAML (default: api/openapi.yaml)
GLULESS_BASE_URL   optional API base; unset → ephemeral mock
```

---

## Gas City pack integration

Importable pack under [`pack/`](pack/):

```text
pack/
  pack.toml                 Pack identity (schema 2)
  formulas/gluless-prove.toml   Formula v2 HOW + [steps.check] exec
  contracts/*.glu           Goals (not Formula identity)
  scripts/gluless-check     check.exec entrypoint
  examples/validation-city  Local formula-show fixture
```

- Import the pack into a city. **Do not** add `[[gluless]]` to `city.toml`.
- **Do not** fork Gas City or invent a seventh primitive.
- Formula `gluless-prove` prepares inputs, then `[steps.check]` runs `scripts/gluless-check` (`mode = "exec"`), which calls `python -m gluless prove …`.
- Pack **CONFIGURES**; Formula **invokes** GluLess at check time. GluLess remains the acceptance contract, not the Formula language.

Operator details: [`pack/README.md`](pack/README.md).

---

## Backlog

Honest gaps (not shipped):

- MCP and A2A Utility adapters
- Approval **resume** after `waiting_for_approval`
- Real response **JSON Schema** validation (CLI currently uses a coarse evidence heuristic for `response.schema valid`)
- Canonical published IR schema (beyond Python dataclasses)
- Planner beyond “first READ / first MUTATION utility”

See also [docs/connections-and-plugins.md](docs/connections-and-plugins.md) for importer status.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
