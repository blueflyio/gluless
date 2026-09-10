# AGENTS.md

## Project

**GluLess** is an agent-native executable contract language and runtime.

**GLU = Goal · Limits · Utilities**

> **The contract is the program. No glue required.**

GluLess lets humans and agents declare:
- the **Goal** — what must become true
- the **Limits** — what authority, constraints, policy, and invariants govern execution
- the **Utilities** — what APIs, tools, agents, and services are available

The runtime determines the execution path. The model does not self-authorize.

---

## Repository layout

```
sdk/python/gluless/       Core SDK: models, compiler, registry, limits, context,
                          bindings, evidence, experience, importers/
sdk/python/tests/         Test suite (pytest)
api/openapi.yaml          Example API spec — annotated with x-gluless-* extensions
mock/mock_server.py       Mock API server (port 8000) for local canary runs
.agents/agents/glu-agent/ Reference AG-UI agent implementation (port 8080)
demo/                     Browser demo UI (no build step)
docs/                     Architecture docs and specification
```

---

## Engineering directive

Build the MVP using the GluLess principle:

**GLU = Goal · Limits · Utilities**

The objective is not to generate more code. It is to reduce glue between intent and execution.

### Decision order

```
DELETE → CONFIGURE → COMPOSE → REUSE → EXTEND → CREATE
```

Before creating anything new, answer:

```
DOES_API_EXIST=
DOES_PROTOCOL_EXIST=
DOES_LIBRARY_EXIST=
CAN_EXISTING_OWNER_BE_EXTENDED=
```

If yes, use it. If incomplete, extend it. Only create when a real gap is proven.

### Limits (what agents must not do)

- Do not duplicate schemas, API clients, models, or utility metadata
- Do not add a new abstraction unless it removes real duplication or establishes a stable boundary
- Do not accept "should work" as completion — prove behavior with tests and runtime evidence
- Do not build around existing APIs — use them; if incomplete, extend them

### Utilities (prefer stable capabilities over implementation-specific behavior)

Prefer:
```
Monitoring.services.list
Work.tasks.claim
Deployment.status
Memory.search
GitLab.mergeRequest.create
```

Over:
```
run shell command
read internal file
query database directly
call undocumented port
```

---

## Engineering model

Think in this order:

```
GOAL      — What must become true?
LIMITS    — What rules, authority, and constraints apply?
UTILITIES — What existing capabilities can achieve it?
EXECUTION — What is the smallest valid path?
EVIDENCE  — What proves it worked?
```

Do not begin with "What code should I write?"  
Begin with "What capability already exists that moves the Goal forward?"

---

## Agent working rules

When modifying this repository:

1. Read current source before proposing architecture
2. Identify the existing owner of the behavior
3. Reuse before creating
4. Write/update tests first for semantic changes (TDD)
5. Make the smallest valid implementation change
6. Run relevant tests (`pytest sdk/python/tests/`)
7. Run the full suite before marking complete
8. Update docs when semantics change
9. Report evidence, not confidence

---

## Evidence reporting (hard rule)

Completion requires proof. For each task report:

### Capability
```
GOAL=
UTILITY=
LIMITS_CHECKED=
REQUEST=
REAL_RESPONSE=
TEST=
RESULT=
EVIDENCE=
```

### Mutations
```
AUTHORITY=
SIDE_EFFECT=
STATE_BEFORE=
STATE_AFTER=
EVIDENCE=
```

A compile is not proof. A rendered screen is not proof. An agent saying "done" is not proof.

---

## Decision rule

When uncertain, favor the option that creates:
- fewer concepts
- fewer dependencies
- fewer hidden behaviors
- stronger interfaces
- better tests
- clearer authority
- more observable execution

GluLess should remove glue, not become another layer of it.
