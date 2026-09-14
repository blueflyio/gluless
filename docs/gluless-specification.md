# GluLess language reference (v0.1)

Product thesis and plan live in [README.md](../README.md) and [PLAN.md](PLAN.md). This file is the **language / IR** reference only — not a second manifesto.

## What a `.glu` file is

A declarative acceptance contract with four authored parts:

| Part | Meaning |
|------|---------|
| **Goal** | Outcome that must become true (`target:`) |
| **Limits** | Allow / deny / require-approval selectors (declaration order, last match wins) |
| **Utilities** | Named capabilities the runtime may bind and call |
| **evidence** | Predicates that must hold for Proven Done |

Standalone `limits { … }` blocks are supported by the parser.

## Computational pipeline (shipped MVP)

```text
.glu → parse → IR (models.py)
     → OpenAPI import → UtilityRegistry
     → authorize (Limits)
     → execute (HTTP binding)
     → verify (evidence + goal) → Result
```

Gas City does not reimplement this pipeline. Pack CONFIGURES; Formula `gluless-prove` `[steps.check]` execs the CLI.

## Limits (operators)

Selectors (exact match, not substring):

- `*` — all
- `Namespace.*` — namespace prefix form used in contracts
- Full utility id (`Monitoring.services.list`)
- Bare final segment / side-effect class / utility type where supported by the evaluator

Rules:

- `deny` / `allow` / `require approval for <selector>`
- Last matching rule wins
- Side effect `unknown` does not inherit `create` authority; deny unless named

`waiting_for_approval` is emitted; **resume is not implemented**.

## Utilities

Today: OpenAPI operations annotated with:

```yaml
x-gluless-name: Monitoring.services.list
x-gluless-type: read          # read | mutation
x-gluless-side-effects: none  # none | create | update | delete | external_message | unknown
x-gluless-exclude: true       # omit from registry
```

Importer: `sdk/python/gluless/importers/openapi.py`. Binding/execution: HTTP only in MVP. MCP / A2A: not shipped — see [connections-and-plugins.md](connections-and-plugins.md).

## Evidence & Result

Evidence clauses in the Goal (e.g. `response.status == 200`, `services observed`) are evaluated after execution. `response.schema valid` is currently a **coarse heuristic**, not full JSON Schema validation.

`Result.status`: `satisfied | blocked | waiting_for_approval | failed`.

CLI prove path prints stage lines (`PARSE=PASS`, …, `PROVEN=YES`).

## IR

The IR has exactly one hand-authored definition: the Pydantic v2 models in
`sdk/python/gluless/models.py`. `api/contract.schema.json` (JSON Schema
2020-12) is **generated** from those models and checked in so that consumers
without Python — the Go and TypeScript SDKs — read a language-neutral contract
rather than reimplementing one.

```text
sdk/python/gluless/models.py   authored      ← change the IR here
        │  python -m gluless.schema --write
        ▼
api/contract.schema.json       generated     ← never hand-edit
```

`tests/test_ir_schema.py` fails if the checked-in file stops matching the
models, so the two cannot drift. `python -m gluless.schema --check` is the same
gate for CI.

Shape: `Contract{ id, ir_version, goals[], limits[], utilities[],
evidence_requirements[] }`, where a `Utility` carries `id`, `namespace`,
`name`, declared `type` and `side_effects`, a `transport`, `auth`, and
`provenance`. Every node sets `additionalProperties: false`: an undeclared key
in a serialized IR document is an error, because the IR carries authority
decisions and must fail closed the way the Limit evaluator does.

`provenance` records where a Utility came from and is **never** consulted for
authority.

Why Pydantic: `ag-ui-protocol` already requires it, so it adds no dependency;
it both validates instances and emits JSON Schema, so one definition serves the
runtime and the published contract.

### Identity of an imported Utility

`id` is `<namespace>.<resource>.<action>`; it is what a Limit selector targets,
so duplicates are a fail-closed import error. Parameter segments are normally
erased (`/city/{name}` and `/city/{id}` name the same capability). Where that
erasure is ambiguous — `/agent/{base}` and `/agent/{dir}/{base}` both reduced
to `agent.read` — the tie-break is a property of the path alone:

> a parameter segment that is **not** immediately preceded by a literal segment
> contributes its name to the action.

So `/agent/{dir}/{base}` is `agent.read.base`, while every path whose
parameters each follow a literal segment is unchanged. `x-gluless-name`
overrides identity outright.

## Non-negotiables (short)

- Limits are deterministic; models do not self-authorize
- Utilities are named capabilities, not ad hoc shell
- Completion requires evidence (`PROVEN=YES`), not a verbal claim
- GluLess is not a Gas City primitive; do not fork Gas City to “add GluLess”

## Upstream composition

OpenAPI, MCP, A2A, AG-UI, Cedar/OPA, secrets, and workflow engines remain upstream owners. GluLess imports or binds; it does not replace them ([OWNERSHIP.md](../OWNERSHIP.md)).
