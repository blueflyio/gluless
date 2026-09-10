# GluLess — Connections, Importers, and Transport Bindings

**The contract is the program. A connection is how the runtime reaches the world.**

---

## Conceptual model

GluLess separates three concerns that most agent frameworks conflate:

```
CONTRACT            What to achieve (Goal) and what is allowed (Limits)
  ↓
IMPORTER            How to project an external API spec into the runtime registry
  ↓
UTILITY REGISTRY    What callable operations exist, their semantics, and their transport
  ↓
BINDING             How to actually call a specific operation at runtime
  ↓
CONNECTION          The configured network target (base URL, auth, transport type)
```

The agent author never describes *how* to call an API. They declare a Goal.  
The runtime resolves which utility satisfies it, checks Limits, and invokes the bound transport.

---

## Importers

Importers project external API specifications into `Utility` objects in the runtime registry.

### Currently implemented: OpenAPI

[`sdk/python/gluless/importers/openapi.py`](file:///Users/flux423/Sites/blueflyio/POCs/Gluless/sdk/python/gluless/importers/openapi.py)

The `OpenAPIImporter` reads an OpenAPI 3.x YAML/JSON spec and produces a list of `Utility` IR objects. Each operation becomes a utility when annotated with `x-gluless-*` extensions:

```yaml
# api/openapi.yaml
/services:
  get:
    operationId: listServices
    x-gluless-name: Monitoring.services.list   # utility ID in the registry
    x-gluless-type: read                        # read | mutation
    x-gluless-side-effects: none                # none | create | update | delete | external_message
    x-gluless-exclude: true                     # omit from registry entirely (e.g. /health)
```

Operations **without** `x-gluless-name` are imported with a derived ID but are filtered out by `_build_registry()` in `agent.py` — only explicitly named utilities enter the runtime.

### Planned importers (not yet implemented)

| Importer | Spec format | Status |
|----------|------------|--------|
| `OpenAPIImporter` | OpenAPI 3.x YAML/JSON | ✅ implemented |
| `MCPImporter` | MCP tool manifest JSON | 🔲 planned |
| `GraphQLImporter` | GraphQL schema SDL | 🔲 planned |
| `GRPCImporter` | Protobuf / gRPC reflection | 🔲 planned |

**To add a new importer**, implement the interface:

```python
class MyImporter:
    def import_spec(self, spec_text: str) -> list[Utility]:
        ...
```

Then call it in `_build_registry()` in `agent.py` before `registry.register()`.

---

## Utility Registry

[`sdk/python/gluless/registry.py`](file:///Users/flux423/Sites/blueflyio/POCs/Gluless/sdk/python/gluless/registry.py)

The registry is the runtime knowledge plane. It stores:

- `utility_id` — canonical `utility://{namespace}/{resource.verb}` URI
- `operation_id` — the human-readable `Namespace.resource.verb` ID used in contracts
- `transport` — method, path, parameters, request body schema, response schemas
- `side_effect` — declared (from spec) and observed (from ExperienceIndex)
- `semantic_capabilities` — domain and resource classification used by FILTER stage

### Modes

| Mode | How to activate | Behaviour |
|------|----------------|-----------|
| In-memory (default for POC) | `UtilityRegistry(registry_path=":memory:")` | Never reads or writes disk |
| Persistent | `UtilityRegistry()` or custom path | Reads/writes `~/.gluless/utility_registry.json` |

> [!IMPORTANT]
> Always use `:memory:` in the agent process. Persistent registries accumulate stale entries from renamed utilities and will pollute the FILTER stage with ghost utilities.

---

## Connections

A **connection** is a configured network target for a transport binding. In the POC, it is a single `API_URL` env var. In a multi-API runtime it would be one entry per imported spec.

### Current connection model

```
env: API_URL=http://localhost:8000/v0    (default)
env: API_TOKEN=...                       (optional bearer/key auth)
```

These are consumed by [`UtilityResolver`](file:///Users/flux423/Sites/blueflyio/POCs/Gluless/sdk/python/gluless/bindings.py) at execution time.

### API endpoints for connection introspection

All endpoints are on the GLU Agent (port 8080):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Agent status, registry count, API URL |
| `GET` | `/utilities` | All utilities projected in the runtime registry |
| `GET` | `/registry` | Full registry dump (debug — all fields per utility) |
| `GET` | `/connections` | Active transport connections (base URLs, spec URIs) |
| `POST` | `/agent` | AG-UI streaming endpoint — accepts GLU contract YAML |

#### `GET /utilities` — example response

```json
{
  "count": 3,
  "utilities": [
    {
      "registryId": "utility://monitoring/services.list",
      "utilityId":  "Monitoring.services.list",
      "type":       "read",
      "sideEffects": "none",
      "transport":  {"method": "GET", "path": "/services"},
      "domain":     "services",
      "sourceUri":  "/path/to/api/openapi.yaml"
    }
  ]
}
```

#### `GET /connections` — example response

```json
{
  "count": 1,
  "connections": [
    {
      "id":      "default",
      "type":    "http",
      "baseUrl": "http://localhost:8000/v0",
      "specUri": "/path/to/api/openapi.yaml",
      "status":  "configured"
    }
  ]
}
```

---

## Transport bindings

[`sdk/python/gluless/bindings.py`](file:///Users/flux423/Sites/blueflyio/POCs/Gluless/sdk/python/gluless/bindings.py)

`UtilityResolver` takes a `Utility` IR object and produces an `ExecutableBinding`. The binding holds everything needed to make a real HTTP call:

- Base server URL
- HTTP method + path (with parameter interpolation)
- Request body construction from inputs
- Response parsing → `{status_code, body, error}`

`ExecutableBinding.execute(inputs: dict)` is synchronous and is run in a thread-pool executor to avoid blocking the async event loop.

### Adding a non-HTTP transport

Implement a new binding class alongside `ExecutableBinding`:

```python
@dataclass
class MCPBinding:
    tool_name: str
    server: str
    
    def execute(self, inputs: dict) -> dict:
        # call MCP tool, return {"status_code": 200, "body": ..., "error": None}
        ...
```

Then add a transport-type branch in `UtilityResolver.resolve()`:

```python
def resolve(self, utility: Utility) -> ExecutableBinding | MCPBinding:
    if utility.transport.type == "mcp":
        return MCPBinding(...)
    return ExecutableBinding(...)  # default HTTP
```

---

## Pipeline: how importers, registry, connections, and bindings compose

```
STARTUP
  OpenAPIImporter.import_spec(yaml)
        ↓ list[Utility]
  UtilityRegistry(:memory:).register(utility, ...)
        ↓ utility://namespace/resource.verb
  _REGISTRY ready

RUN CONTRACT
  _compile_contract(yaml)
        → resolves utility IDs from _REGISTRY
  RESOLVE stage
        → all_registry_utilities = _PROJECTED_UTILITIES
  FILTER stage
        → goal_domains from goal LHS expression
        → _capability_domain(u) must intersect goal_domains
  AUTHORIZE stage
        → LimitEvaluator.evaluate(u) → allow | deny
  EXECUTE stage
        → UtilityResolver(_API_URL).resolve(u) → ExecutableBinding
        → binding.execute({}) → {status_code, body, error}
        → world_state updated from body
  VERIFY stage
        → _evaluate_evidence(req, http_status, body, world_state)
        → all evidence passed → phase = proven
```

---

## Running the stack locally

```bash
# 1. Mock API (port 8000)
cd mock/
uvicorn mock_server:app --port 8000

# 2. GLU Agent (port 8080)
cd .agents/agents/glu-agent/
PYTHONPATH=[WORKSPACE-ROOT]/POCs/Gluless/sdk/python \
  .venv/bin/uvicorn agent:app --port 8080

# 3. Verify connections
curl http://localhost:8080/connections
curl http://localhost:8080/utilities

# 4. Open demo UI
open demo/index.html
```

Target any real API by setting `API_URL` before starting the agent:

```bash
API_URL=https://api.your-service.com/v1 \
  .venv/bin/uvicorn agent:app --port 8080
```

---

## Extending with a new API provider

1. **Add the OpenAPI spec** (or write `x-gluless-*` annotations on an existing one)
2. **Set `x-provider-name`** at the spec root
3. **Annotate each operation** with `x-gluless-name`, `x-gluless-type`, `x-gluless-side-effects`
4. **Set `API_URL`** to the server base URL
5. **Write a contract** that references your new utility IDs:

```yaml
id: my-contract
goals:
  - id: goal-1
    expression: "orders.listed == true"
limits:
  - id: deny-all
    action_pattern: "deny *"
  - id: allow-list
    action_pattern: "allow Commerce.orders.list"
utilities:
  - Commerce.orders.list
evidence_requirements:
  - id: ev-ok
    assertion: "response.status == 200"
```

No code changes required. The importer, registry, and bindings work from the spec.
