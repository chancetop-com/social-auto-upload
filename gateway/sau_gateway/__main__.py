import argparse
import asyncio
import os

import uvicorn
from .app import create_app
from .database import migrate


class GatewayServer(uvicorn.Server):
    def __init__(self, host, port):
        self.stopping = asyncio.Event()
        super().__init__(uvicorn.Config(create_app(self.stopping), host=host, port=port,
                                        workers=1, timeout_graceful_shutdown=20))

    async def shutdown(self, sockets=None):
        # Uvicorn waits for open HTTP requests before ASGI lifespan shutdown.
        self.stopping.set()
        await super().shutdown(sockets=sockets)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "serve"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()
    if args.command == "migrate":
        migrate(os.environ["GATEWAY_DATABASE_URL"])
    else:
        GatewayServer(args.host, args.port).run()


if __name__ == "__main__":
    main()
