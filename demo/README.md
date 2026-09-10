# GluLess Demo

**GLU = Goal · Limits · Utilities**

A runnable AG-UI streaming demo for the GluLess contract runtime.

---

## What this is

A self-contained proof of concept: a Python AG-UI agent that accepts a GLU contract, compiles it, enforces limits, executes declared utilities, and streams all execution state back to a web UI over SSE.

No framework. No glue. The contract is the program.

---

## Structure

```
demo/
  index.html     — UI (no build step, open directly)
  style.css      — Design system
  app.js         — AG-UI SSE client

.agents/agents/glu-agent/
  AGENT.md       — Agent wire contract and protocol spec
  agent.py       — FastAPI AG-UI endpoint
  contract.yaml  — Example GLU contract
  requirements.txt
  .venv/         — Python virtual environment
```

---

## Run

### 1. Start the GLU Agent

```bash
cd [WORKSPACE-ROOT]/POCs/Gluless/.agents/agents/glu-agent
.venv/bin/uvicorn agent:app --reload --port 8080
```

The agent exposes:
- `POST /agent` — AG-UI streaming endpoint (SSE)
- `GET  /health` — liveness check
- `GET  /utilities` — declared utility registry
- `GET  /docs` — FastAPI auto-docs

### 2. Open the UI

```bash
open [WORKSPACE-ROOT]/POCs/Gluless/demo/index.html
```

Or serve it:

```bash
python3 -m http.server 3000 --directory demo/
# open http://localhost:3000
```

Click **"View contract"** to inspect the loaded contract, then **"Run contract"** to execute.

---

## AG-UI Events Emitted

| Event               | Meaning                               |
|---------------------|---------------------------------------|
| `RUN_STARTED`       | Contract run begins                   |
| `TEXT_MESSAGE_START`| Narrative message opens               |
| `TEXT_MESSAGE_CHUNK`| Streaming text delta                  |
| `TEXT_MESSAGE_END`  | Narrative message closes              |
| `STATE_SNAPSHOT`    | Full contract + execution state       |
| `STATE_DELTA`       | Incremental state change (JSON Patch) |
| `RUN_FINISHED`      | Run complete (with or without warning)|
| `RUN_ERROR`         | Fatal error (compile, limit violation)|

---

## Evidence

The agent never claims completion without evidence. Each run produces:

```
GOAL=        contract goal expression
UTILITY=     utility ID invoked
LIMITS_CHECKED= limit patterns evaluated
REQUEST=     HTTP request made
REAL_RESPONSE= raw response
TEST=        evidence assertion
RESULT=      pass / fail
EVIDENCE=    HTTP status + observation
```

---

## Connecting to a real API

Set the agent URL before starting:

```bash
AGENT_API_BASE_URL=http://your-api-host/v0 \
  .venv/bin/uvicorn agent:app --reload --port 8080
```

---

## A2UI

This agent is A2UI-ready. To wire A2UI surface rendering, follow `.agents/skills/agui/ag-ui-a2ui-integration/SKILL.md`.
