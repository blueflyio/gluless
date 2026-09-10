"""
Mock API Server
===============

A minimal FastAPI server that satisfies the Monitoring API contract defined in
api/openapi.yaml. This is the target system for the GluLess end-to-end canary.

Run on port 8000 (the default endpoint expected by the GLU agent):

    cd mock/
    pip install fastapi uvicorn
    uvicorn mock_server:app --reload --port 8000

The GLU agent runs on port 8080. Both must be running for a successful PROVEN run.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Monitoring API Mock",
    version="0.2.0",
    description="Mock Monitoring API for GluLess end-to-end canary runs.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_START = time.time()

# ── Data ──────────────────────────────────────────────────────────
_SERVICES: dict[str, dict] = {
    "auth-service": {
        "name": "auth-service",
        "status": "healthy",
        "version": "v1.2.0",
        "instances": 3,
    },
    "data-pipeline": {
        "name": "data-pipeline",
        "status": "degraded",
        "version": "v0.9.1",
        "instances": 1,
    },
    "api-gateway": {
        "name": "api-gateway",
        "status": "healthy",
        "version": "v2.0.4",
        "instances": 2,
    },
}


# ── Request / Response models ─────────────────────────────────────
class ServiceCreate(BaseModel):
    status: str = "healthy"


class NudgeRequest(BaseModel):
    force: bool = False


# ── Routes ────────────────────────────────────────────────────────

@app.get("/v0/health")
def health_check():
    return {
        "status": "ok",
        "version": "0.2.0",
        "uptime": int(time.time() - _START),
    }


@app.get("/v0/services")
def list_services():
    """
    GET /v0/services — satisfies Monitoring.services.list (read, no side effects).

    A successful 200 response with at least one service satisfies the goal
    predicate: services.listed == true.
    """
    return list(_SERVICES.values())


@app.post("/v0/services/{name}", status_code=201)
def create_service(name: str, body: ServiceCreate):
    """
    POST /v0/services/{name} — satisfies Monitoring.service.create (mutation, create).

    This operation is DENIED under the demo contract's 'deny *' limit.
    The GluLess runtime will deny this utility in the AUTHORIZE stage —
    it will never reach this endpoint during a standard demo run.
    Its presence in the registry is what makes the denied-path evidence real.
    """
    if name in _SERVICES:
        raise HTTPException(status_code=409, detail="Service already exists")
    _SERVICES[name] = {"name": name, "status": body.status, "version": "v0.0.1", "instances": 0}
    return _SERVICES[name]


@app.post("/v0/sessions/{session_id}/nudge")
def nudge_session(session_id: str, body: NudgeRequest):
    """
    POST /v0/sessions/{id}/nudge — Monitoring.sessions.nudge (mutation, external_message).
    Also DENIED by the demo contract.
    """
    return {
        "status": "nudged",
        "sessionId": session_id,
        "message": f"Session {session_id} nudged (force={body.force})",
    }
