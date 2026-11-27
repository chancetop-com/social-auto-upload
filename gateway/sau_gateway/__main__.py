import argparse
import os

import uvicorn
from .database import migrate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "serve"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8080, type=int)
    args = parser.parse_args()
    if args.command == "migrate":
        migrate(os.environ["GATEWAY_DATABASE_URL"])
    else:
        uvicorn.run("sau_gateway.app:create_app", factory=True, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
