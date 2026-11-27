import asyncio
import os
from secrets import compare_digest
from uuid import UUID, uuid4

import httpx

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .preparation import enqueue_preparation, take_preparation
from .database import Conflict, Missing, Store
from .models import CheckTarget, CheckTask, Claim, Preparation, PublishTask, Result, Session, Start


def authorized(token):
    bearer = HTTPBearer(auto_error=False)

    def check(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not compare_digest(token.encode(), credentials.credentials.encode()):
            raise HTTPException(401, "Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    return [Depends(check)]


def create_app(stopping=None):
    if stopping is None:
        stopping = asyncio.Event()
    desktop_token = os.environ["GATEWAY_DESKTOP_TOKEN"]
    internal_token = os.environ["GATEWAY_INTERNAL_TOKEN"]
    if not (desktop_token.strip() and internal_token.strip()) or desktop_token == internal_token:
        raise ValueError("Set separate nonempty Gateway desktop and internal tokens")
    desktop, internal = authorized(desktop_token), authorized(internal_token)
    store = Store(os.environ["GATEWAY_DATABASE_URL"])
    app = FastAPI(title="social-media-web-api", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(Missing)
    async def missing(request, exc):
        return JSONResponse({"detail": "Unknown session or occurrence"}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, exc):
        return JSONResponse({"detail": "Session does not hold this claim"}, status_code=409)

    @app.get("/health-check")
    def ready():
        if stopping.is_set():
            raise HTTPException(503, "Gateway is draining")
        store.ready()
        return {"status": "ready"}

    @app.post("/session", dependencies=desktop)
    def report(session: Session):
        return store.report(session)

    @app.get("/internal/sessions/{session_id}", dependencies=internal)
    def get_session(session_id: UUID):
        return store.session(session_id)

    @app.post("/session/{session_id}/self-check", dependencies=desktop)
    def self_check(session_id: UUID, target: CheckTarget):
        session = store.session(session_id)
        if session["mode"] != "self-check":
            raise HTTPException(409, "Use a dedicated self-check session")
        task = CheckTask(**target.model_dump(), action="check", workflowId=f"check-{uuid4()}",
                    requiredCapability=f"{target.platform}.check", contractVersion=1, release=session["release"])
        return store.enqueue(task, target_session=session_id)

    @app.post("/internal/occurrences", dependencies=internal)
    def enqueue(task: CheckTask | PublishTask):
        return store.enqueue(task)

    @app.post("/internal/preparations", dependencies=internal)
    def prepare(offer: Preparation):
        enqueue_preparation(store, offer)
        return {"accepted": True}

    @app.get("/internal/occurrences/{workflow_id:path}", dependencies=internal)
    def lookup(workflow_id: str):
        return store.get(workflow_id)

    @app.post("/publish-task/claim", dependencies=desktop)
    async def claim(body: Claim, request: Request):
        deadline = asyncio.get_running_loop().time() + body.waitSeconds
        while not stopping.is_set() and not await request.is_disconnected():
            task = await asyncio.to_thread(store.claim, body.sessionId)
            if not task and body.acceptPreparation:
                task = await asyncio.to_thread(take_preparation, store, body.sessionId)
            remaining = deadline - asyncio.get_running_loop().time()
            if task or remaining <= 0:
                return {"task": task}
            try:
                await asyncio.wait_for(stopping.wait(), timeout=min(remaining, 0.5))
            except asyncio.TimeoutError:
                pass
        return {"task": None}

    @app.post("/publish-task/start", dependencies=desktop)
    def start(body: Start):
        if stopping.is_set():
            raise HTTPException(503, "Gateway is draining")
        task = store.reserve_start(body)
        base = os.environ.get("POSTIZ_INTERNAL_URL", "").rstrip("/")
        if task is None:
            raise HTTPException(409, "Desktop no longer eligible")
        if not base:
            raise HTTPException(503, "Postiz authorization is unavailable")
        try:
            with httpx.Client(timeout=10, trust_env=False) as client:
                response = client.post(base + "/internal/browser-publishing/authorize-start",
                                       headers={"Authorization": "Bearer " + internal_token},
                                       json={key: task[key] for key in ("workflowId", "postId", "organizationId")})
            if response.status_code in (403, 409):
                store.deny_start(body)
                raise HTTPException(response.status_code, "Postiz declined this occurrence")
            response.raise_for_status()
            latest = PublishTask.model_validate(response.json())
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "Postiz authorization is uncertain")
        granted = store.start(body, latest)
        if granted is None:
            raise HTTPException(409, "Target or desktop changed before start")
        return {"task": granted}

    @app.post("/publish-task/result", dependencies=desktop)
    def finish(result: Result):
        return store.finish(result)

    return app
