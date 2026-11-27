import asyncio
from dataclasses import dataclass, field
import os
import re
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from . import __version__
from .providers import DEFAULT_BASES, inventory


PLATFORMS = ("rednote", "xiaohongshu", "tiktok", "instagram")
CAPABILITIES = [{"platform": platform, "action": "check"} for platform in PLATFORMS]
DEFAULT_GATEWAY = "https://social-media-web-api.connexup-dev.net"


def endpoint(value, *, local=False):
    parts = urlsplit(value)
    loopback = parts.hostname in {"127.0.0.1", "localhost", "::1"}
    if (not parts.hostname or parts.username or parts.password or parts.query or parts.fragment
            or parts.scheme not in {"https", "http"} or (parts.scheme == "http" and not loopback)
            or (local and not loopback)):
        raise ValueError("Use HTTPS for the Gateway and a loopback address for each Local API")
    return value.rstrip("/")


@dataclass
class Settings:
    gateway: str
    token: str = field(repr=False)
    cli: tuple[str, ...]
    capacity: int
    providers: dict[str, tuple[str, str]] = field(repr=False)

    @classmethod
    def from_env(cls, env):
        token = env.get("SAU_DESKTOP_TOKEN", "").strip()
        if not token:
            raise ValueError("SAU_DESKTOP_TOKEN is required")
        cli_path = env.get("SAU_CLI_PATH")
        python = env.get("SAU_CLI_PYTHON", sys.executable)
        cli = (cli_path,) if cli_path else (python, "-I", "-m", "sau_cli")
        if not Path(cli[0]).is_absolute():
            raise ValueError("The paired CLI path must be absolute")
        capacity = int(env.get("WORKER_MAX_CONCURRENCY", 1))
        if capacity < 1:
            raise ValueError("WORKER_MAX_CONCURRENCY must be positive")
        configured = [p for p in DEFAULT_BASES if env.get(p.upper() + "_API_KEY")]
        if "SAU_PROVIDERS" in env:
            configured = [name.strip() for name in env["SAU_PROVIDERS"].split(",") if name.strip()]
        providers = {}
        for name in configured:
            if name not in DEFAULT_BASES:
                raise ValueError("Unknown provider in SAU_PROVIDERS")
            base = endpoint(env.get(name.upper() + "_API_BASE", DEFAULT_BASES[name]), local=True)
            providers[name] = (base, env.get(name.upper() + "_API_KEY", ""))
        return cls(endpoint(env.get("SAU_GATEWAY_URL", DEFAULT_GATEWAY)), token, cli, capacity, providers)


class Worker:
    def __init__(self, settings, client, *, self_check=False):
        self.settings = settings
        self.client = client
        self.self_check = self_check
        self.session_id = str(uuid4())
        self.providers = []
        self.active = set()
        self.cli_release = None
        self.connected = False
        self.report_lock = asyncio.Lock()

    @property
    def paired(self):
        return self.cli_release == __version__

    async def post(self, path, body):
        response = await self.client.post(self.settings.gateway + path, json=body,
                                          headers={"Authorization": "Bearer " + self.settings.token}, timeout=40)
        response.raise_for_status()
        self.connected = True
        return response.json()

    def command(self, args, provider=None, timeout=120):
        env = os.environ.copy()
        for key in ("MLX_API_TOKEN", "SAU_DESKTOP_TOKEN", "GATEWAY_DESKTOP_TOKEN", "GATEWAY_INTERNAL_TOKEN",
                    "GATEWAY_DATABASE_URL", "ADSPOWER_API_KEY", "BITBROWSER_API_KEY", "ADSPOWER_API_BASE", "BITBROWSER_API_BASE"):
            env.pop(key, None)
        if provider:
            base, key = self.settings.providers[provider]
            env.update({provider.upper() + "_API_KEY": key, provider.upper() + "_API_BASE": base})
        return subprocess.run([*self.settings.cli, *args], env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              encoding="utf-8", errors="replace", timeout=timeout)

    async def report(self, *, discover=True):
        async with self.report_lock:
            if discover:
                if not self.paired:
                    try:
                        proc = await asyncio.to_thread(self.command, ["--version"], timeout=15)
                        match = re.fullmatch(r"sau ([A-Za-z0-9.+!-]{1,120})", proc.stdout.strip())
                        self.cli_release = match.group(1) if match and proc.returncode == 0 else None
                    except (OSError, subprocess.TimeoutExpired):
                        self.cli_release = None
                self.providers = await asyncio.gather(*[
                    inventory(self.client, name, base, key)
                    for name, (base, key) in self.settings.providers.items()
                ])
            return await self.post("/session", {
                "sessionId": self.session_id, "mode": "self-check" if self.self_check else "worker",
                "contractVersion": 1, "release": __version__, "cliRelease": self.cli_release,
                "capacity": self.settings.capacity,
                "freeSlots": max(0, self.settings.capacity - len(self.active)),
                "capabilities": CAPABILITIES if self.paired else [], "providers": self.providers,
            })

    async def claim(self, wait_seconds=15):
        response = await self.post("/publish-task/claim", {"sessionId": self.session_id, "waitSeconds": wait_seconds})
        return response["task"]

    async def execute(self, task):
        provider, platform = task["provider"], task["platform"]
        profile_id = task["profileId"]
        visible = any(p["provider"] == provider and p["available"]
                      and any(profile["profileId"] == profile_id for profile in p["profiles"]) for p in self.providers)
        evidence = {"cloudConnected": True, "cliInvoked": False, "profileVisible": visible,
                    "platformLogin": "unknown", "exitCode": None}
        if (not self.paired or not visible or platform not in PLATFORMS or task["action"] != "check"
                or task["contractVersion"] != 1 or task["requiredCapability"] != platform + ".check"
                or task["release"] != __version__):
            return evidence
        try:
            proc = await asyncio.to_thread(self.command, [platform, "check", "--profile-id=" + profile_id], provider)
        except subprocess.TimeoutExpired:
            evidence["cliInvoked"] = True
            return evidence
        except OSError:
            return evidence
        evidence.update(cliInvoked=True, exitCode=proc.returncode)
        if proc.returncode == 0 and "valid" in proc.stdout.splitlines():
            evidence["platformLogin"] = "valid"
        elif proc.returncode == 10:
            evidence["platformLogin"] = "login-required"
        return evidence

    async def finish(self, record):
        workflow_id = record["workflowId"]
        self.active.add(workflow_id)
        try:
            # A lost slot-status reply cannot invalidate a committed claim.
            try:
                await self.report(discover=False)
            except httpx.HTTPError:
                pass
            receipt = await self.execute(record["task"])
            return await self.post("/publish-task/result", {"sessionId": self.session_id,
                                   "workflowId": workflow_id, "receipt": receipt})
        finally:
            self.active.remove(workflow_id)
            try:
                await self.report(discover=False)
            except httpx.HTTPError:
                pass

    async def check(self, provider, profile_id, platform):
        await self.report()
        queued = await self.post(f"/session/{self.session_id}/self-check", {
            "provider": provider, "profileId": profile_id, "platform": platform})
        record = await self.claim(5)
        if not record or record["workflowId"] != queued["workflowId"]:
            raise RuntimeError("Self-check was not claimed")
        return await self.finish(record)

    async def run(self):
        running = set()
        while True:
            try:
                completed = {job for job in running if job.done()}
                running -= completed
                for job in completed:
                    try:
                        job.result()
                    except httpx.HTTPError:
                        print("Gateway result acknowledgement unavailable", file=sys.stderr, flush=True)
                await self.report()
                if len(running) >= self.settings.capacity:
                    await asyncio.wait(running, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                else:
                    record = await self.claim()
                    if record:
                        running.add(asyncio.create_task(self.finish(record)))
            except httpx.HTTPError:
                self.connected = False
                await asyncio.sleep(2)
