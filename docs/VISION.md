# GluLess — Design Principles

**GLU = Goal · Limits · Utilities**

> **The contract is the program. No glue required.**

---

## Engineering objective

The objective is not to generate more code. It is to reduce glue between intent and execution.

Ship the smallest working vertical slice that proves real execution and makes the next capability easier to add than the first.

Favor:
- working outcomes over architecture expansion
- API-first execution
- stable, reusable interfaces
- test-driven development
- observable execution
- evidence-backed completion

Do not confuse infrastructure growth with product progress.

---

## Decision order

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

Only create when a real gap is proven.

---

## Engineering constraints

- Do not create scripts, services, databases, or wrappers when an existing interface can do the job
- Do not couple behavior directly to filesystem layout, shell commands, or internal implementation details when a stable API can own that contract
- Do not duplicate schemas, API clients, models, or auth logic
- Do not introduce a new abstraction unless it removes real duplication or establishes a necessary stable boundary
- Do not accept "should work" as completion — prove behavior with tests and runtime evidence

---

## API first

Every service must have a clear interface.

Prefer:
```
Contract → Utility → Stable API → Service
```

Not:
```
Contract → shell → filesystem → database → hidden implementation detail
```

Use REST CRUD where the domain is resource-oriented: `LIST`, `GET`, `CREATE`, `UPDATE`, `DELETE`.  
Use explicit actions only where CRUD does not represent the operation correctly.

If an API exists, use it. If incomplete, extend it. Do not build around it.

---

## Utilities

Prefer stable, named capabilities:

```
Monitoring.services.list
Work.tasks.claim
Deployment.status
Memory.search
GitLab.mergeRequest.create
```

Over implementation-specific behavior:

```
run shell command
read internal file
query database directly
call undocumented port
```

Utilities should expose clear contracts:

```
INPUT=
OUTPUT=
AUTHORITY=
SIDE_EFFECTS=
ERRORS=
```

The caller cares about the capability. Not the implementation behind it.

---

## Ownership

Put behavior with the correct owner:

- UI-specific behavior → UI
- shared presentation → shared UI component
- service contract → shared client / SDK
- business capability → owning service
- cross-service execution → governed runtime

One authoritative owner per concept.

---

## TDD

For semantic changes:
1. add a failing test
2. prove the failure
3. make the smallest correction
4. prove the test passes
5. run the broader suite

---

## CI

CI must be:
- deterministic
- fast
- observable
- ordered cheap → expensive

---

## Evidence

Completion requires proof.

For each capability:

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

A compile is not proof. A rendered screen is not proof. An agent saying "done" is not proof.

---

## MVP standard

Each completed slice must:
1. use real APIs
2. reuse existing capabilities
3. reduce glue
4. leave behind tests and observable evidence
5. make the next slice easier
