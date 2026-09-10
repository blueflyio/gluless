# GLU Agent

**Identity**: `glu-agent`  
**Version**: 0.2.0  
**Protocol**: AG-UI (streaming SSE)  
**Runtime**: GluLess Execution Plane  

---

## Mission

The GLU Agent is the reference implementation of a GluLess-native agent.

It:
- Accepts a GLU contract (Goal · Limits · Utilities) via the AG-UI `/agent` endpoint
- Compiles the contract using the Python GluLess SDK
- Executes each stage: RESOLVE → FILTER → AUTHORIZE → EXECUTE → VERIFY
- Streams AG-UI events back to the client in real time
- Reports Evidence and a terminal phase (`proven` or `unresolved`) on completion

> The agent never executes outside declared utilities.  
> The agent never acts outside declared limits.  
> The agent never claims completion without verifiable evidence.

---

## API endpoints

| Method | Path          | Description                                                     |
|--------|---------------|-----------------------------------------------------------------|
| `GET`  | `/health`     | Agent status, registry count, API URL, spec path               |
| `GET`  | `/utilities`  | All utilities projected in the runtime registry                 |
| `GET`  | `/connections`| Active transport connections (base URL, spec URI)               |
| `GET`  | `/registry`   | Full registry dump — all fields per utility (debug)             |
| `POST` | `/agent`      | AG-UI streaming endpoint — accepts GLU contract YAML            |

---

## AG-UI wire contract

### `POST /agent`

```
Content-Type: application/json
Accept: text/event-stream
```

**Request body**

```json
{
  "threadId": "<uuid>",
  "runId":    "<uuid>",
  "messages": [
    {
      "role":    "user",
      "content": "<GLU contract YAML as string>"
    }
  ],
  "context": [],
  "tools":   [],
  "state":   null
}
```

**Streamed events (SSE)**

| Event type           | When                                        |
|----------------------|---------------------------------------------|
| `RUN_STARTED`        | Immediately on run start                    |
| `TEXT_MESSAGE_START` | Before streaming any text chunk             |
| `TEXT_MESSAGE_CHUNK` | Each execution narrative line               |
| `TEXT_MESSAGE_END`   | After last chunk                            |
| `STATE_SNAPSHOT`     | When contract is compiled (full state)      |
| `STATE_DELTA`        | On each stage transition or utility result  |
| `RUN_FINISHED`       | On successful completion with evidence      |
| `RUN_ERROR`          | On limit violation, compile error, or fatal |

---

## GLU contract format

The agent accepts contract YAML as the user message content:

```yaml
id: my-contract
goals:
  - id: goal-1
    expression: "services.listed == true"
    description: "List all services and verify they are reachable"
limits:
  - id: limit-deny-all
    action_pattern: "deny *"
    description: "Deny any action not explicitly permitted"
  - id: limit-allow-list
    action_pattern: "allow Monitoring.services.list"
    description: "Permit listing services"
utilities:
  - Monitoring.services.list
evidence_requirements:
  - id: ev-http-ok
    assertion: "response.status == 200"
    description: "API responded with HTTP 200"
```

---

## Agent state shape (STATE_SNAPSHOT / STATE_DELTA)

```typescript
interface GluAgentState {
  contractId:         string | null;
  phase:              "idle" | "resolving" | "filtering" | "authorizing"
                    | "executing" | "verifying" | "proven" | "unresolved" | "error";
  goals:              Goal[];
  limits:             Limit[];
  utilities:          Utility[];
  context_projection: { registry_total: number; goal_compatible: number; limit_permitted: number; };
  plan:               PlanStep[];
  observations:       Observation[];
  decision_paths:     DecisionPath[];
  evidence:           Evidence[];
  error:              string | null;
}
```

---

## Files

| File             | Purpose                                     |
|------------------|---------------------------------------------|
| `AGENT.md`       | This file — wire spec and running notes     |
| `agent.py`       | FastAPI server implementing all endpoints   |
| `contract.yaml`  | Example contract for local canary runs      |
| `requirements.txt` | Python dependencies                       |

---

## Running

```bash
# From the repo root
cd .agents/agents/glu-agent/

# Start mock API (port 8000)
cd ../../mock && \
  ../agents/glu-agent/.venv/bin/uvicorn mock_server:app --port 8000 &

# Start GLU agent (port 8080)
cd ../agents/glu-agent && \
  PYTHONPATH=[REPO-ROOT]/sdk/python \
  .venv/bin/uvicorn agent:app --port 8080

# Verify
curl http://localhost:8080/health
curl http://localhost:8080/utilities

# Run demo UI
open [REPO-ROOT]/demo/index.html
```

---

## Evidence template

```
GOAL=           contract goal expression
UTILITY=        utility ID invoked
LIMITS_CHECKED= limit patterns evaluated (order matters — last match wins)
REQUEST=        HTTP method + URL
REAL_RESPONSE=  actual HTTP status + body excerpt
EVIDENCE=       assertion + pass/fail
RESULT=         proven | unresolved
```
