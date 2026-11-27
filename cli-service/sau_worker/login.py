"""Per-user, interactive native login registration for one installed bundle."""
import csv
import hashlib
import os
from pathlib import Path
import plistlib
import subprocess
import xml.etree.ElementTree as ET


def label(root):
    return "net.connexup.social-auto-upload." + hashlib.sha256(os.fsencode(root)).hexdigest()[:16]


def registration(root, *, windows, user):
    if not windows:
        return plistlib.dumps({
            "Label": label(root), "RunAtLoad": True, "LimitLoadToSessionType": "Aqua",
            "KeepAlive": {"SuccessfulExit": False},
            "ProgramArguments": [str(root / "program/runtime/bin/python3.11"),
                                 "-IB", "-m", "sau_worker.desktop", "_supervise"],
            "WorkingDirectory": str(root),
            "StandardOutPath": str(root / "state/worker.log"),
            "StandardErrorPath": str(root / "state/worker.log"),
        })
    task = ET.Element("Task", version="1.2", xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task")
    trigger = ET.SubElement(ET.SubElement(task, "Triggers"), "LogonTrigger")
    ET.SubElement(trigger, "UserId").text = user
    principal = ET.SubElement(ET.SubElement(task, "Principals"), "Principal", id="Operator")
    for key, value in {"UserId": user, "LogonType": "InteractiveToken", "RunLevel": "LeastPrivilege"}.items():
        ET.SubElement(principal, key).text = value
    settings = ET.SubElement(task, "Settings")
    for key, value in {"MultipleInstancesPolicy": "IgnoreNew", "DisallowStartIfOnBatteries": "false",
                       "StopIfGoingOnBatteries": "false", "ExecutionTimeLimit": "PT0S"}.items():
        ET.SubElement(settings, key).text = value
    retry = ET.SubElement(settings, "RestartOnFailure")
    ET.SubElement(retry, "Interval").text = "PT1M"
    ET.SubElement(retry, "Count").text = "999"
    action = ET.SubElement(ET.SubElement(task, "Actions", Context="Operator"), "Exec")
    ET.SubElement(action, "Command").text = str(root / "program/runtime/python.exe")
    ET.SubElement(action, "Arguments").text = "-IB -m sau_worker.desktop _supervise"
    ET.SubElement(action, "WorkingDirectory").text = str(root)
    return ET.tostring(task, encoding="utf-16", xml_declaration=True)


def native(args, *, check=True):
    return subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, check=check)


def native_login(root, *, remove=False, start=False):
    name = label(root)
    if os.name == "nt":
        who = subprocess.check_output(["whoami.exe", "/user", "/fo", "csv", "/nh"], text=True)
        user = next(csv.reader([who.strip()]))[-1]
        name += "-" + user
        xml = root / "state/login-task.xml"
        exists = native(["schtasks.exe", "/query", "/tn", name], check=False).returncode == 0
        if remove:
            if exists:
                native(["schtasks.exe", "/delete", "/f", "/tn", name])
            xml.unlink(missing_ok=True)
            return
        data = registration(root, windows=True, user=user)
        if not exists or not xml.exists() or xml.read_bytes() != data:
            xml.write_bytes(data)
            native(["schtasks.exe", "/create", "/tn", name, "/xml", str(xml), "/f"])
        if start:
            native(["schtasks.exe", "/run", "/tn", name])
    else:
        domain = f"gui/{os.getuid()}"
        service = f"{domain}/{name}"
        directory = Path.home() / "Library/LaunchAgents"
        plist = directory / (name + ".plist")
        loaded = native(["launchctl", "print", service], check=False).returncode == 0
        if remove:
            if loaded:
                native(["launchctl", "bootout", service])
            plist.unlink(missing_ok=True)
            return
        data = registration(root, windows=False, user=None)
        if not plist.exists() or plist.read_bytes() != data:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            from .state import atomic_write
            atomic_write(plist, data.decode("utf-8"))
        if not loaded:
            native(["launchctl", "bootstrap", domain, str(plist)])
        elif start:
            native(["launchctl", "kickstart", service])


def start_browsers(settings):
    """Launch each configured desktop app independently; readiness comes from inventory."""
    for provider in settings.providers:
        path = os.environ.get(provider.upper() + "_APP_PATH")
        try:
            if os.name == "nt":
                candidates = {"bitbrowser": ["BitBrowser/BitBrowser.exe"],
                              "adspower": ["AdsPower Global/AdsPower Global.exe", "adspower_global/AdsPower Global.exe"]}
                if not path:
                    path = next((str(Path(base) / rel) for key in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)")
                                 if (base := os.environ.get(key)) for rel in candidates[provider]
                                 if (Path(base) / rel).is_file()), None)
                if not path:
                    raise FileNotFoundError
                os.startfile(path)
            else:
                native(["open", "-g", "-a", path or {"bitbrowser": "BitBrowser", "adspower": "AdsPower Global"}[provider]])
        except (OSError, subprocess.CalledProcessError):
            print(f"Could not launch {provider}; waiting for its Local API", flush=True)
