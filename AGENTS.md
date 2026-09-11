# AGENTS.md

## Project

**GluLess** — executable acceptance contracts: **Goal · Limits · Utilities**.

Human entry: [README.md](README.md). Plan: [docs/PLAN.md](docs/PLAN.md). Index: [llms.txt](llms.txt).

Proven Done = `gluless prove` / pack check reaches `PROVEN=YES` with evidence. Chat is not proof.

## Layout

```text
sdk/python/gluless/   Runtime + parser + OpenAPI importer
sdk/python/tests/     pytest
api/openapi.yaml      Example OpenAPI (x-gluless-* annotations)
pack/                 Gas City pack + Formula gluless-prove
docs/PLAN.md          Phased status (only plan doc)
docs/gluless-specification.md   Language / IR reference
```

## Rules

1. Read source before proposing architecture.
2. Prefer DELETE → CONFIGURE → COMPOSE → REUSE → EXTEND → CREATE.
3. Prefer named Utilities (`Monitoring.services.list`) over shell/filesystem glue.
4. Semantic changes: failing test first, then smallest fix, then suite green.
5. Update README / PLAN when ship status or blockers change.
6. Report evidence (`GOAL=`, `UTILITY=`, `LIMITS_CHECKED=`, `RESULT=`, `EVIDENCE=`), not confidence.
7. Do not fork Gas City; do not add `[[gluless]]` to `city.toml`; GluLess is not a Formula.

## Decision rule

Favor fewer concepts, fewer dependencies, stronger interfaces, clearer authority, observable execution. GluLess should remove glue, not become another layer of it.
