import asyncio
import os
from secrets import compare_digest
from uuid import UUID, uuid4

import httpx

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import leases, releases
from .wakeups import Wakeups
from .database import Conflict, Missing, Store
from .models import CheckTarget, CheckTask, Claim, LeaseCommand, LeaseRelease, PublishTask, Result, Session, Start


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
    wakeups = Wakeups()
    app = FastAPI(lifespan=wakeups.lifespan, title="social-media-web-api", docs_url=None, redoc_url=None, openapi_url=None)

    releases.register(app, store, desktop, internal)

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
    async def self_check(session_id: UUID, target: CheckTarget):
        session = await asyncio.to_thread(store.session, session_id)
        if session["mode"] != "self-check":
            raise HTTPException(409, "Use a dedicated self-check session")
        task = CheckTask(**target.model_dump(), action="check", workflowId=f"check-{uuid4()}",
                    requiredCapability=f"{target.platform}.check", contractVersion=1, release=session["release"])
        record = await asyncio.to_thread(store.enqueue, task, target_session=session_id)
        await wakeups.publish()
        return record

    @app.post("/internal/occurrences", dependencies=internal)
    async def enqueue(task: CheckTask | PublishTask):
        record = await asyncio.to_thread(store.enqueue, task)
        await wakeups.publish()
        return record

    @app.get("/internal/occurrences/{workflow_id:path}", dependencies=internal)
    def lookup(workflow_id: str):
        return store.get(workflow_id)

    @app.post("/publish-task/claim", dependencies=desktop)
    async def claim(body: Claim, request: Request):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + body.waitSeconds
        # FastAPI has consumed the claim body. The next ASGI message signals disconnect.
        disconnect = asyncio.create_task(request.receive())
        stop = asyncio.create_task(stopping.wait())
        try:
            with wakeups.register() as event:
                while not stopping.is_set() and not disconnect.done():
                    event.clear()  # A notification during the query remains set when it returns.
                    task = await asyncio.to_thread(store.claim, body.sessionId)
                    remaining = deadline - loop.time()
                    if task or remaining <= 0:
                        return {"task": task}
                    notice = asyncio.create_task(event.wait())
                    try:
                        await asyncio.wait((notice, disconnect, stop), timeout=min(remaining, wakeups.recheck),
                                           return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        notice.cancel()
                        await asyncio.gather(notice, return_exceptions=True)
            return {"task": None}
        finally:
            disconnect.cancel()
            stop.cancel()
            await asyncio.gather(disconnect, stop, return_exceptions=True)

    @app.post("/profile-lease/renew", dependencies=desktop)
    def renew(body: LeaseCommand):
        with store.connect() as db:
            expiry = leases.renew(db, body, store.lease_policy)
            if expiry is None:
                raise Conflict()
            return {"expiresAt": expiry}

    def complete_transaction(body):
        with store.connect() as db:
            idle = leases.complete(db, body)
            if idle is None:
                raise Conflict()
            return {"idle": idle}

    @app.post("/profile-lease/complete", dependencies=desktop)
    async def complete(body: LeaseCommand):
        status = await asyncio.to_thread(complete_transaction, body)
        await wakeups.publish()
        return status

    def release_transaction(body):
        with store.connect() as db:
            if not leases.release(db, body):
                raise Conflict()
            return {"released": True}

    @app.post("/profile-lease/release", dependencies=desktop)
    async def release(body: LeaseRelease):
        status = await asyncio.to_thread(release_transaction, body)
        await wakeups.publish()
        return status

    @app.post("/publish-task/start", dependencies=desktop)
    def start(body: Start):
        if stopping.is_set():
            raise HTTPException(503, "Gateway is draining")
        authorization = store.reserve_start(body)
        base = os.environ.get("POSTIZ_INTERNAL_URL", "").rstrip("/")
        if authorization is None:
            raise HTTPException(409, "Desktop no longer eligible")
        if not base:
            raise HTTPException(503, "Postiz authorization is unavailable")
        try:
            with httpx.Client(timeout=10, trust_env=False) as client:
                response = client.post(base + "/internal/browser-publishing/authorize-start",
                                       headers={"Authorization": "Bearer " + internal_token},
                                       json=authorization)
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
    async def finish(result: Result):
        record = await asyncio.to_thread(store.finish, result)
        await wakeups.publish()
        return record

    return app
