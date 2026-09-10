# Ownership

## Mission

GluLess is an agent-native executable contract language and runtime designed to compose outcome, authority, capabilities, execution, and proof into one canonical program without ad hoc glue code.

## Owns

* Authoritative definition of the GluLess agent-native contract language and specifications.
* The canonical GluLess Intermediate Representation (IR) schema.
* The core parser, compiler, and validator translating `.glu` contracts to IR.
* Standard runtime interfaces (Parser, Validator, Importer, Resolver, Evaluator, Planner, Executor, Observer, EventSink, EvidenceStore).
* The OpenAPI importer and HTTP execution adapter.
* Deterministic Limits validation and Goal evaluation logic.

## Does Not Own

* Upstream capability formats like OpenAPI, JSON Schema, GraphQL, gRPC, or MCP (it imports them).
* Inter-agent protocols like A2A (it composes with them).
* Frontend communication protocols like AG-UI (it adapts execution events to them).
* Policy engines like Cedar or OPA/Rego (it delegates rule checking to them).
* Durable workflow runtimes like Temporal or AWS Step Functions (it delegates/delegates execution to them).
* Secrets management or credential storage (kept external).

## Upstream Authorities

* OpenAPI Initiative (OpenAPI Specification)
* Model Context Protocol (MCP tools and lifecycle)
* Agent2Agent Protocol (A2A task transport)
* Cedar Policy Language (deterministic authorization)
* Open Policy Agent (Rego policy validation)

## Downstream Consumers

* Agent runtimes, rigs, and orchestration layers requiring structured outcome contracts and deterministic limit enforcement.

## Extension Boundary

* Extend this project to add core language features, improve parser/validation coverage, enrich IR schemas, or add standard capability/transport adapters.
* Do not extend this project to build custom databases, distributed schedulers, custom auth/secrets providers, or general-purpose UI frameworks.

## Data / Runtime Authority

* Execution state remains transient within the runtime; long-lived state or audit trails are dispatched to external EvidenceStores or EventSinks.

## Configuration Authority

* Environment variables and external secret providers; no hardcoded credentials.

## Secret Authority

* 1Password, where applicable.

## Deprecated / Legacy Names

* None.

## Escalation Rule

* Prove upstream, prove duplication, identify owner, then implement.
