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

Canonical in-repo IR is the Python dataclasses in `sdk/python/gluless/models.py`. A separate published schema document is not shipped yet ([PLAN.md](PLAN.md)).

## Non-negotiables (short)

- Limits are deterministic; models do not self-authorize
- Utilities are named capabilities, not ad hoc shell
- Completion requires evidence (`PROVEN=YES`), not a verbal claim
- GluLess is not a Gas City primitive; do not fork Gas City to “add GluLess”

## Upstream composition

OpenAPI, MCP, A2A, AG-UI, Cedar/OPA, secrets, and workflow engines remain upstream owners. GluLess imports or binds; it does not replace them ([OWNERSHIP.md](../OWNERSHIP.md)).
