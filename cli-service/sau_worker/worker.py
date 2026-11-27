import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from . import __version__
from .children import Children
from .state import read, write
from .rollout import installation, progress_body
from .instagram_events import instagram_command
from .publish import receipt as publish_receipt
from .platforms import PUBLISH_CAPABILITIES, publish_args
from .leases import command_lease, local_close_marker
from .maintenance import daily_cleanup
from .media import predownload_args
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
    dev_aliases: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, env):
        token = env.get("SAU_DESKTOP_TOKEN", "").strip()
        if not token:
            raise ValueError("SAU_DESKTOP_TOKEN is required")
        cli_path = env.get("SAU_CLI_PATH")
        python = env.get("SAU_CLI_PYTHON", sys.executable)
        cli = (cli_path,) if cli_path else (python, "-I", "-X", "utf8", "-m", "sau_cli")
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
        aliases = tuple(dict.fromkeys(alias.strip() for alias in env.get("SAU_DEV_CHROME_ALIASES", "").split(",")
                                     if alias.strip()))
        return cls(endpoint(env.get("SAU_GATEWAY_URL", DEFAULT_GATEWAY)), token, cli, capacity, providers, aliases)


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
        root = os.environ.get("SAU_INSTALL_ROOT")
        self.state = Path(root) / "state" if root else None
        self.installation = installation(Path(root)) if self.state else None
        self.generation = os.environ.get("SAU_WORKER_GENERATION")
        self.children = Children(self.state) if self.state else None

    @property
    def draining(self):
        if not self.generation:
            return False
        from .supervisor import ending
        return ending(self.state, self.generation) or (
            not self.self_check and self.upgrade.get("step") in ("draining", "staging", "returning"))

    @property
    def upgrade(self):
        return read(self.state / "upgrade.json") if self.installation else {}

    @property
    def free_slots(self):
        if self.draining or (not self.self_check and self.upgrade):
            return 0
        occupied = self.children.count(excluding=self.session_id) if self.children else 0
        return max(0, self.settings.capacity - len(self.active) - occupied)

    @property
    def ready(self):
        return self.connected and self.paired and self.free_slots > 0 and any(
            p["available"] and p["profiles"] for p in self.providers)

    def save_status(self):
        if self.generation and not self.self_check:
            write(self.state / "worker.json", {"sessionId": self.session_id, "pid": os.getpid(),
                  "claimReady": bool(self.ready), "capacity": self.settings.capacity,
                  "active": len(self.active), "updatedAt": time.time()})

    async def withdraw_on_drain(self):
        while not self.draining:
            await asyncio.sleep(.1)
        try:
            await self.report(discover=False)
        except httpx.HTTPError:
            pass

    async def pause(self, seconds):
        until = time.monotonic() + seconds
        while not self.draining and time.monotonic() < until:
            await asyncio.sleep(min(.25, max(0, until - time.monotonic())))

    @property
    def paired(self):
        return self.cli_release == __version__

    async def post(self, path, body):
        response = await self.client.post(self.settings.gateway + path, json=body,
                                          headers={"Authorization": "Bearer " + self.settings.token}, timeout=40)
        response.raise_for_status()
        self.connected = True
        try:
            body = response.json()
        except ValueError as exc:
            raise httpx.RemoteProtocolError("Gateway returned invalid JSON", request=response.request) from exc
        if not isinstance(body, dict):
            raise httpx.RemoteProtocolError("Gateway returned an invalid object", request=response.request)
        return body

    def command(self, args, provider=None, timeout=120, on_processing=None):
        env = os.environ.copy()
        env.pop("SAU_WINDOW_CLOSED_FILE", None)
        if provider == "local-chrome" and (marker := local_close_marker.get()):
            env["SAU_WINDOW_CLOSED_FILE"] = str(marker)
        env["PYTHONIOENCODING"] = "utf-8"
        for key in ("MLX_API_TOKEN", "SAU_DESKTOP_TOKEN", "GATEWAY_DESKTOP_TOKEN", "GATEWAY_INTERNAL_TOKEN",
                    "GATEWAY_DATABASE_URL", "ADSPOWER_API_KEY", "BITBROWSER_API_KEY", "ADSPOWER_API_BASE", "BITBROWSER_API_BASE"):
            env.pop(key, None)
        if provider and provider != "local-chrome":
            base, key = self.settings.providers[provider]
            env.update({provider.upper() + "_API_KEY": key, provider.upper() + "_API_BASE": base})
        env.pop("SAU_EVENT_NONCE", None)
        if on_processing:
            env["SAU_EVENT_NONCE"] = uuid4().hex
        with self.open_command(args, env) as proc:
            if on_processing:
                return instagram_command(proc, env["SAU_EVENT_NONCE"], on_processing)
            out, err = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    @contextmanager
    def open_command(self, args, env):
        if self.children and self.settings.cli[-2:] == ("-m", "sau_cli") and args != ["--version"]:
            with self.children.launch(self.session_id, self.settings.cli[:-2], args, env) as proc:
                yield proc
            return
        with subprocess.Popen([*self.settings.cli, *args], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace") as proc:
            try:
                yield proc
            except BaseException:
                proc.kill()
                proc.wait()
                raise

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
                if self.settings.dev_aliases:
                    self.providers.append({"provider": "local-chrome", "available": True,
                                           "profiles": [{"profileId": alias, "name": alias}
                                                        for alias in self.settings.dev_aliases]})
            capabilities = CAPABILITIES if self.self_check else [*CAPABILITIES, *PUBLISH_CAPABILITIES]
            reply = await self.post("/session", {
                **({"installation": self.installation} if self.installation else {}),
                "sessionId": self.session_id, "mode": "self-check" if self.self_check else "worker",
                "contractVersion": 1, "release": __version__, "cliRelease": self.cli_release,
                "preparedStarts": self.paired and not self.self_check,
                "capacity": self.settings.capacity,
                "freeSlots": self.free_slots,
                "capabilities": capabilities if self.paired else [], "providers": self.providers,
            })

            self.save_status()
            return reply

    async def claim(self, wait_seconds=15):
        response = await self.post("/publish-task/claim", {"sessionId": self.session_id, "waitSeconds": wait_seconds,
                                                          "acceptPreparation": not self.self_check})
        return response["task"]

    def target(self, task):
        provider, profile_id = task["provider"], task["profileId"]
        if provider == "local-chrome":
            if profile_id in self.settings.dev_aliases:
                return ["--account=" + profile_id, "--local-browser=chrome"]
            return None
        if provider in self.settings.providers and self.settings.providers[provider][1]:
            if any(p["provider"] == provider and p["available"]
                   and any(profile["profileId"] == profile_id for profile in p["profiles"]) for p in self.providers):
                return ["--profile-id=" + profile_id]
        return None

    async def execute(self, task):
        provider, platform = task["provider"], task["platform"]
        target = self.target(task)
        visible = target is not None
        evidence = {"cloudConnected": True, "cliInvoked": False, "profileVisible": visible,
                    "platformLogin": "unknown", "exitCode": None}
        if (not self.paired or not visible or platform not in PLATFORMS or task["action"] != "check"
                or task["contractVersion"] != 1 or task["requiredCapability"] != platform + ".check"
                or task["release"] != __version__):
            return evidence
        try:
            proc = await asyncio.to_thread(self.command, [platform, "check", *target], provider)
        except subprocess.TimeoutExpired:
            evidence["cliInvoked"] = True
            return evidence
        except OSError:
            return evidence
        evidence.update(cliInvoked=True, exitCode=proc.returncode)
        if proc.returncode == 0 and "valid" in proc.stdout.splitlines():
            evidence["platformLogin"] = "valid"
        elif proc.returncode == 10:
            evidence["platformLogin"] = ("verification-required" if proc.stderr.splitlines()[-1:] == ["login_reason=verification"]
                                         else "login-or-verification-required")
        return evidence

    async def publish(self, task):
        failed = {"outcome": "failed", "cliInvoked": False, "exitCode": None}
        target = self.target(task)
        if (not self.paired or not target or task["contractVersion"] != 1 or task["release"] != __version__
                or {"platform": task["platform"], "action": task["action"]} not in PUBLISH_CAPABILITIES
                or task["requiredCapability"] != task["platform"] + "." + task["action"]):
            return failed
        try:
            args = [*publish_args(task, target), "--prepared-media-only"]
            # The CLI owns its publish budget and extends it for an intentional earliest-click wait.
            kwargs = {}
            if task["platform"] == "instagram":
                loop = asyncio.get_running_loop()

                async def report_processing():
                    try:
                        await self.post("/publish-task/result", {
                            "sessionId": self.session_id, "workflowId": task["workflowId"],
                            "receipt": {"outcome": "processing", "cliInvoked": True, "exitCode": None}})
                    except httpx.HTTPError:
                        pass  # Progress is advisory. The final receipt still belongs to the original claim.

                kwargs["on_processing"] = lambda: asyncio.run_coroutine_threadsafe(report_processing(), loop)
            proc = await asyncio.to_thread(self.command, args, task["provider"], timeout=None, **kwargs)
        except (KeyError, TypeError, ValueError, OSError):
            return failed
        return publish_receipt(proc, task)

    async def prepare_start(self, claimed):
        identity = ("workflowId", "postId", "channelId", "organizationId", "bindingId",
                    "provider", "profileId", "platform", "contractVersion", "release")
        task = claimed
        while True:
            try:
                ready = await asyncio.to_thread(self.command, [*predownload_args(task), "--wait"], timeout=None)
                failed = bool(ready.returncode)
            except (ValueError, OSError):
                failed = True
            response = await self.post("/publish-task/start", {
                "sessionId": self.session_id, "workflowId": claimed["workflowId"],
                "preparedMedia": task["media"], "mediaFailed": failed})
            refreshed = "prepare" in response
            current = response.get("prepare" if refreshed else "task")
            if not isinstance(current, dict) or any(current.get(k) != claimed.get(k) for k in identity):
                raise httpx.RemoteProtocolError("Gateway returned an inconsistent occurrence")
            if not refreshed:
                if failed or current.get("media") != task["media"]:
                    raise httpx.RemoteProtocolError("Gateway granted media that was not prepared")
                return current
            task = current

    async def finish(self, record):
        workflow_id = record["workflowId"]
        if record.get("operation") == "prepare":
            task = record["task"]
            if (self.paired and not self.self_check and self.target(task)
                    and task.get("workflowId") == workflow_id and task.get("release") == __version__
                    and task.get("contractVersion") == 1):
                try:
                    # This command returns on enqueue. The paired CLI owns its acknowledgement budget.
                    await asyncio.to_thread(self.command, predownload_args(task), timeout=None)
                except (KeyError, TypeError, ValueError, OSError):
                    pass  # Publish will obtain the current manifest on the executing machine.
            return
        if workflow_id in self.active:
            return
        self.active.add(workflow_id)
        self.save_status()
        try:
            async with command_lease(self, record):
                claimed = record["task"]
                if claimed["action"] == "check":
                    try:
                        await self.report(discover=False)
                    except httpx.HTTPError:
                        pass
                    receipt = await self.execute(claimed)
                else:
                    # Only the current start response grants permission to create a child.
                    # A lost response, conflict or restart never execs from the stale claim.
                    await self.report()
                    task = await self.prepare_start(claimed)
                    receipt = await self.publish(task)
            return await self.post("/publish-task/result", {"sessionId": self.session_id,
                                   "workflowId": workflow_id, "receipt": receipt})
        finally:
            self.active.remove(workflow_id)
            self.save_status()
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

    async def validate_release(self):
        batch = self.upgrade
        if not batch or batch.get("step") != "validating":
            return False
        if self.installation.get("batchId") != batch["batchId"]:
            return True
        response = await self.post("/session/release/progress", progress_body(
            self.state.parent, batch, "switched", sessionId=self.session_id))
        receipt = read(self.state / "release-check-result.json")
        if not response["active"] or (
            receipt.get("batchId") == batch["batchId"] and receipt.get("sessionId") == self.session_id
        ):
            return True
        saved = read(self.state / "release-check-target.json")
        provider = os.environ.get("SAU_RELEASE_CHECK_PROVIDER") or saved.get("provider")
        profile = os.environ.get("SAU_RELEASE_CHECK_PROFILE") or saved.get("profile")
        platform = os.environ.get("SAU_RELEASE_CHECK_PLATFORM") or saved.get("platform")
        if provider and profile and platform and self.paired:
            checker = Worker(self.settings, self.client, self_check=True)
            try:
                result = await checker.check(provider, profile, platform)
            except RuntimeError:
                return True
            if result["state"] == "succeeded":
                write(self.state / "release-check-result.json", {"batchId": batch["batchId"],
                      "sessionId": self.session_id, "checkWorkflowId": result["workflowId"]})
        return True

    async def run(self):
        maintenance = asyncio.create_task(daily_cleanup(self))
        try:
            await self.poll()
        finally:
            maintenance.cancel()
            await asyncio.gather(maintenance, return_exceptions=True)

    async def poll(self):
        running = set()
        while not self.draining:
            try:
                completed = {job for job in running if job.done()}
                running -= completed
                for job in completed:
                    try:
                        job.result()
                    except httpx.HTTPError:
                        print("Gateway result acknowledgement unavailable", file=sys.stderr, flush=True)
                await self.report()
                if self.draining:
                    break
                if await self.validate_release():
                    await self.pause(5)
                    continue
                if self.ready and len(running) < self.settings.capacity:
                    record = await self.claim()
                    if record:
                        running.add(asyncio.create_task(self.finish(record)))
                        # Reserve the local active slot before the next session advertisement.
                        await asyncio.sleep(0)
                elif running:
                    await asyncio.wait(running, timeout=15, return_when=asyncio.FIRST_COMPLETED)
                else:
                    await self.pause(2)
            except httpx.HTTPError:
                self.connected = False
                self.save_status()
                await self.pause(2)
        # A poll already in flight can have committed one final claim. Finish and
        # attempt its result in the original session before yielding to maintenance.
        try:
            await self.report(discover=False)
        except httpx.HTTPError:
            pass
        await asyncio.gather(*running, return_exceptions=True)
