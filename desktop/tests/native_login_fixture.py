"""Stub macOS native commands before starting an installed worker in a disposable HOME."""
import sys


def stub_commands(directory):
    directory.mkdir(exist_ok=True)
    for name in ("launchctl", "open"):
        exe = directory / name
        exe.write_text(f"#!{sys.executable}\n" + NATIVE)
        exe.chmod(0o755)
    return str(directory) + ":/usr/bin:/bin:/usr/sbin"


NATIVE = """
import json, os, plistlib, subprocess, sys
from pathlib import Path
home=Path(os.environ["HOME"])
args=sys.argv[1:]
with (home/'commands').open('a') as f: print(json.dumps([Path(sys.argv[0]).name,*args]), file=f)
if Path(sys.argv[0]).name == 'open': sys.exit()
registration=home/'registered'
if args[0]=='print': sys.exit(0 if registration.exists() else 113)
if args[0]=='bootout': registration.unlink(missing_ok=True); sys.exit()
if args[0]=='bootstrap': registration.write_text(args[2])
spec=plistlib.loads(Path(registration.read_text()).read_bytes())
with open(spec["StandardOutPath"],"ab") as log:
    subprocess.Popen(spec['ProgramArguments'],cwd=spec['WorkingDirectory'],stdout=log,stderr=log,
                     stdin=subprocess.DEVNULL,start_new_session=True)
"""
