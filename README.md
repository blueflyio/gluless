# GluLess

**An agent-native executable contract language and runtime.**

**GLU = Goal · Limits · Utilities**

> **The contract is the program.**

GluLess exists to remove the integration glue between intent and execution.

Traditional programming languages are designed primarily for humans to describe how a computer should perform work. AI agents change that relationship. An agent often does not need every HTTP request, loop, wrapper, serializer, retry, state adapter, or orchestration step spelled out. It needs a precise description of the outcome, the boundaries governing execution, and the capabilities available to reach that outcome.

GluLess moves the abstraction layer upward.

Instead of forcing agents to continually generate and maintain glue code, humans and agents declare:

- the **Goal** — what must become true;
- the **Limits** — what authority, constraints, policies, approvals, and invariants govern execution;
- the **Utilities** — what APIs, tools, agents, services, models, resources, and event sources are available.

The runtime determines the execution path.

---

## Why GluLess

Modern application and agent code frequently looks like:

```text
intent
→ client library
→ API wrapper
→ auth plumbing
→ serializer
→ retry logic
→ model mapping
→ orchestration
→ state adapter
→ UI binding
```

Much of this is glue.

GluLess aims to reduce that layer by making stable capabilities and executable contracts the primary abstraction.

Instead of:

```python
response = requests.get("/services")
response.raise_for_status()
services = response.json()

for s in services:
    if s["status"] != "healthy":
        ...
```

GluLess supports:

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

The contract defines the outcome and boundaries.

The runtime determines how to satisfy it.

---

# GLU

## Goal

**What must become true?**

Goals describe desired outcomes rather than unnecessary implementation steps.

Examples:

```text
service is healthy
task is completed
artifact exists
incident is resolved
deployment succeeds
customer request is satisfied
```

A Goal is the destination.

---

## Limits

**What governs execution?**

Limits include:

```text
authority
permissions
constraints
policies
approvals
budgets
safety requirements
invariants
time boundaries
resource boundaries
```

Capability availability does not imply permission.

An agent may know how to perform an operation while still being prohibited from performing it.

Example:

```glu
limits {
    deny *
    allow Work.tasks.read
    allow Work.tasks.claim
    require approval for Deployment.promote
    deny Infrastructure.destroy
}
```

Limits are enforced by the runtime, not left to model judgment alone.

The evaluation model is **declaration order, last match wins**:

```text
deny *                  ← matches everything
allow Work.tasks.read   ← overrides for this specific utility → ALLOWED
```

Everything else only matched `deny *` → DENIED. Neither guess nor model judgment. The runtime decides.

Selectors name what they govern. There is no substring matching:

```text
*                     everything
Work.*                a namespace or prefix
Work.tasks.claim      one utility id
claim                 a bare word: the final id segment, a side-effect class
                      (read, create, update, delete, external_message, ...)
                      or a utility type (read, mutation)
```

`require approval for <selector>` is a third effect. The run stops with status
`waiting_for_approval` instead of executing; resuming after approval is not yet implemented.

A utility whose side effect is `unknown` (an RPC-style POST such as `.../{id}/kill` that
carries no `x-gluless-side-effects`) is denied unless a limit names it. Unknown never
inherits the authority of `create`.

---

## Utilities

**What may the agent use?**

Utilities are stable capabilities exposed by the environment.

Examples:

```text
OpenAPI operations
HTTP APIs
MCP tools
A2A agents
event streams
models
repositories
search services
infrastructure services
databases behind governed APIs
human approval interfaces
```

A Utility describes what can be done, not how it is implemented internally.

For example:

```text
Monitoring.services.list
```

may resolve to an HTTP API today and a different transport later without changing the GluLess contract.

---

# Architecture

```text
Human / Agent Intent
        |
        v
     GluLess
 Goal + Limits + Utilities
        |
        v
   Typed GluLess IR
        |
        v
   Execution Graph
        |
   +----+-----+---------+
   |          |         |
 OpenAPI     MCP       A2A
   |          |         |
 Service     Tool      Agent
   +----------+---------+
              |
              v
       Events / Evidence
              |
              v
            Result
```

GluLess sits above implementation languages.

Python, Swift, Rust, Go, JavaScript, Java, and other languages remain useful beneath stable service interfaces.

GluLess is not intended to replace them.

It makes them implementation details behind capabilities.

---

# Pipeline

Every contract execution runs through five stages:

```text
RESOLVE   → project Utilities from registry (OpenAPI importer → UtilityRegistry)
FILTER    → retain only goal-relevant candidates (capability domain match)
AUTHORIZE → evaluate each candidate against Limits (declaration order, last match wins)
EXECUTE   → invoke permitted Utilities via real HTTP / MCP / A2A bindings
VERIFY    → evaluate evidence requirements and goal predicate against world state
```

Final states:

```text
PROVEN      all evidence requirements satisfied; goal predicate true
UNRESOLVED  execution failed, evidence incomplete, or goal predicate false
DENIED      no Utility survived AUTHORIZE; execution never reached
```

---

# API First

GluLess favors stable machine-readable interfaces.

Prefer:

```text
GluLess
→ Utility
→ API
→ Service
```

over:

```text
GluLess
→ shell
→ filesystem
→ internal process
→ undocumented database
```

Direct shell, filesystem, or database access may exist as explicit Utilities, but should not be the default integration model.

If an API exists, use it.

If incomplete, extend it.

Do not build around it.

---

# Interface Over Implementation

A contract should depend on:

```text
Work.tasks.list
Monitoring.services.inspect
Memory.search
Deployment.status
```

not on:

```text
which framework implements it
which database stores it
which internal port serves it
which language it uses
which container runs it
```

Stable interfaces make implementations replaceable.

---

# Canonical IR

The GluLess Intermediate Representation is the real language contract.

Human-readable `.glu` source is one representation.

Agents may operate directly on structured IR.

The IR should be:

- typed;
- deterministic;
- serializable;
- versioned;
- inspectable;
- diffable;
- auditable;
- implementation-independent.

Conceptually:

```text
.glu source
    ↓
Parser
    ↓
Typed GluLess IR
    ↓
Validated Capability Graph
    ↓
Execution Graph
    ↓
Runtime
```

Human readability matters.

Machine-native structure matters more.

---

# Runtime Responsibilities

The runtime owns:

```text
parsing
type validation
Utility discovery
Utility resolution
authority checks
Limit enforcement
planning
execution
timeouts
retries
approvals
events
artifacts
evidence
results
```

The runtime should not own business-specific behavior that belongs in contracts or Utilities.

---

# Agent-Native, Not LLM-Everywhere

GluLess is designed for AI agents, but deterministic problems should remain deterministic.

Use deterministic systems for:

```text
parsing
typing
schema validation
authorization
Limit enforcement
serialization
execution accounting
```

Use AI for:

```text
planning
reasoning
Utility selection
interpretation
adaptation
recovery
```

A model may propose an action.

The runtime decides whether the action is valid and authorized.

---

# Authority and Approval

Authority is part of the executable contract.

Human approval is a first-class execution state.

An execution may enter:

```text
WAITING_FOR_APPROVAL
```

with:

```text
requested action
reason
actor
required approver
relevant context
expiration
```

Execution resumes only after valid approval.

Human-in-the-loop is governance, not an exception path.

---

# Events and Evidence

Agent execution must be observable.

Minimum event families may include:

```text
execution.started
execution.completed
execution.failed

goal.evaluated
goal.satisfied
goal.unsatisfied

utility.resolved
utility.started
utility.completed
utility.failed

limit.checked
limit.violated

approval.requested
approval.granted
approval.denied
```

Success is not:

```text
agent said "done"
```

A structured result should include:

```text
status
goal status
actions attempted
actions completed
events
artifacts
errors
evidence
```

The system should be able to answer:

```text
What happened?
Who acted?
What Goal were they pursuing?
What Utility was used?
Under what authority?
What changed?
What proves the result?
```

---

# Protocol Reuse

GluLess should compose existing protocols rather than recreate them.

Preferred integrations include:

```text
OpenAPI / HTTP
MCP
A2A
AG-UI
GraphQL
gRPC
CloudEvents
SSE
WebSocket
```

Conceptually:

```text
OpenAPI operation → Utility
MCP tool          → Utility
A2A agent/task    → Utility
GluLess event     → AG-UI
```

External systems do not need to use GluLess internally.

Interface compatibility is what matters.

---

# OpenAPI First

The first Utility adapter is OpenAPI.

Given any OpenAPI spec, GluLess derives typed Utilities:

```text
GET  /services        →  Monitoring.services.list
POST /deployments     →  Deployment.deployments.create
```

The importer derives:

```text
operation id
HTTP method
path
parameters
request schema
response schema
authentication requirements
error responses
```

Per-operation `x-gluless-name` / `x-gluless-type` / `x-gluless-side-effects` extensions
allow the API contract to declare its GluLess identity. The OpenAPI spec is an
authoritative API contract, not an independent GluLess registry. The importer
projects it into the runtime registry.

Do not hand-code duplicate models when the source interface already defines them.

---

# Initial MVP

The first implementation is intentionally small.

In scope:

```text
Parser
Typed IR
Validator
OpenAPI Utility importer
Utility registry
Goal evaluator
Limits evaluator (declaration order, last match wins)
Simple planner
HTTP executor
Event log
Evidence/result model
CLI
Tests
```

Explicitly out of scope:

```text
IDE
visual programming
custom database
custom scheduler
custom message broker
custom authentication system
custom secrets manager
custom vector database
general-purpose UI framework
complex multi-agent orchestration
new transport protocols
```

Reuse existing systems instead.

---

# First Vertical Slice

Do not expand scope before this works end-to-end:

```text
OpenAPI document
→ import operation
→ produce typed Utility
→ parse contract
→ validate
→ resolve Utility
→ execute HTTP request
→ validate response
→ evaluate Goal
→ emit events
→ produce evidence
→ return structured result
```

Required proof:

```text
PARSE=PASS
TYPECHECK=PASS
UTILITY_IMPORT=PASS
UTILITY_RESOLUTION=PASS
HTTP_EXECUTION=PASS
RESPONSE_VALIDATION=PASS
GOAL_EVALUATION=PASS
EVENTS=PASS
EVIDENCE=PASS
RESULT=PROVEN
```

---

# Design Principles

Use this decision order:

```text
DELETE
→ CONFIGURE
→ COMPOSE
→ REUSE
→ EXTEND
→ CREATE
```

Before adding code, ask:

```text
DOES_STANDARD_EXIST=
DOES_PROTOCOL_EXIST=
DOES_LIBRARY_EXIST=
DOES_API_EXIST=
CAN_EXISTING_OWNER_BE_EXTENDED=
```

Only create something new after a real gap is established.

---

# Testing

Use test-driven development for semantic behavior.

For defects:

1. add a failing test;
2. prove failure;
3. implement the smallest correction;
4. prove the test passes;
5. run the broader suite.

Core test areas:

```text
parser
IR serialization
type validation
Utility import
Utility resolution
Limits enforcement (declaration order, last match wins)
authority
Goal evaluation
HTTP execution
error translation
events
approval lifecycle
evidence
results
```

Core tests should not depend on live external services.

---

# Security

Never put secrets in GluLess source.

Integrate with established identity and secret providers.

Do not build a secrets manager.

Never print secrets in:

```text
logs
events
results
traces
tests
snapshots
```

---

# Where GluLess sits in the Bluefly stack

GluLess is not an agent definition, a discovery protocol, or a policy engine.

```text
OSSA           defines the agent: identity, capabilities, tools, policy bindings
DUADP          finds the agent
MCP / A2A      connect the agent to tools and to other agents
GluLess        states the governed outcome an agent is asked to achieve:
               Goal, Limits, Utilities, and the evidence that proves completion
Cedar /        decide whether a proposed action is authorized and record the
ContractPlane  decision; GluLess Limits bind to them, they do not replace them
Runtime        executes
```

An OSSA agent can accept a GluLess contract as its unit of work. A GluLess Utility can be
an OSSA agent reached through A2A and discovered through DUADP. The word "contract" in
GluLess means the executable outcome contract; ContractPlane is the enforcement and
evidence plane that GluLess Limits delegate to.

---

# Status

The MVP vertical slice runs end to end against a mock API under test (`sdk/python/tests`).

```text
RESOLVE    Utilities projected from OpenAPI via OpenAPIImporter → UtilityRegistry
FILTER     Goal-relevant candidates selected by capability domain
AUTHORIZE  Limits evaluated in declaration order (last match wins); mutations denied by default
EXECUTE    Real HTTP call; real response
VERIFY     Goal predicate re-observed from the API; content-addressed evidence (SHA-256)
RESULT     satisfied | blocked | waiting_for_approval | failed
```

Not yet done: response schema validation, a planner beyond "first
mutation utility", approval resume, MCP and A2A adapters, a canonical IR schema.

The `.glu` parser (`sdk/python/gluless/parser.py`) is syntax-only: Goal, Limits,
Utilities, and Evidence blocks become `models.py` IR. No semantic validation.

The implementation proved three things:

1. APIs become typed Utilities via the OpenAPI importer — no hand-coded metadata.
2. Goals and Limits govern agent-selected execution — the runtime decides, not the model.
3. Execution is observable and auditable — every decision is traceable to a limit, a utility, and an evidence record.

Next: canonical IR schema, MCP tool adapter, A2A agent adapter, approval resume.

## License

Apache License 2.0. See [LICENSE](LICENSE).

---

# Working Principle

**GLU = Goal · Limits · Utilities**

> **The contract is the program.**

**No glue required.**
