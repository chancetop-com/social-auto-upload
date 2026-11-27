import argparse
import asyncio
import json
import os
import ssl
import sys

import httpx

from .providers import DEFAULT_BASES
from .worker import PLATFORMS, Settings, Worker


async def launch(args):
    settings = Settings.from_env(os.environ)
    ca_file = os.environ.get("SAU_GATEWAY_CA_FILE")
    verify = ssl.create_default_context(cafile=ca_file) if ca_file else True
    async with httpx.AsyncClient(trust_env=False, verify=verify) as client:
        worker = Worker(settings, client, self_check=args.command == "check")
        if args.command == "run":
            await worker.run()
            return 0
        try:
            record = await worker.check(args.provider, args.profile_id, args.platform)
        except (httpx.HTTPError, RuntimeError):
            print(json.dumps({"cloudConnected": worker.connected, "receiptConfirmed": False,
                              "cliPaired": worker.paired, "sessionId": worker.session_id}))
            return 1
        if not any(item["provider"] == args.provider and item["available"] for item in worker.providers):
            print(f"Provider unavailable: {args.provider}", file=sys.stderr)
        print(json.dumps(record, ensure_ascii=False))
        return 0 if record["state"] == "succeeded" else 1


def main():
    parser = argparse.ArgumentParser(prog="cli-service")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    check = commands.add_parser("check", help="claim and report a check on this desktop")
    check.add_argument("--provider", required=True, choices=[*DEFAULT_BASES, "local-chrome"])
    check.add_argument("--profile-id", required=True)
    check.add_argument("--platform", required=True, choices=PLATFORMS)
    try:
        return asyncio.run(launch(parser.parse_args()))
    except ValueError as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
