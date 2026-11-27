"""Compatibility entry point for running python sau_cli.py from a checkout."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
position = next((i for i, path in enumerate(sys.path) if Path(path).resolve() == root), 0)
sys.path.insert(position, str(root / "cli"))
from cli import sau_cli as implementation

if __name__ == "__main__":
    raise SystemExit(implementation.main())

# Preserve the module API for callers importing sau_cli from this directory.
sys.modules[__name__] = implementation
