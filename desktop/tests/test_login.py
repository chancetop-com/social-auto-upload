import plistlib
import xml.etree.ElementTree as ET

from sau_worker.login import registration


def test_native_registration_only_runs_in_browser_users_interactive_login(tmp_path):
    root = tmp_path / "Worker root"
    mac = plistlib.loads(registration(root, windows=False, user="fixture"))
    assert mac["LimitLoadToSessionType"] == "Aqua" and mac["RunAtLoad"]
    assert mac["ProgramArguments"] == [str(root / "program/runtime/bin/python3.11"),
                                       "-IB", "-m", "sau_worker.desktop", "_supervise"]
    assert not mac["KeepAlive"]["SuccessfulExit"]
    task = ET.fromstring(registration(root, windows=True, user="S-1-5-21-fixture"))
    def value(query):
        return task.findtext(query, namespaces={"": "http://schemas.microsoft.com/windows/2004/02/mit/task"})
    assert value("Triggers/LogonTrigger/UserId") == "S-1-5-21-fixture"
    assert value("Principals/Principal/LogonType") == "InteractiveToken"
    assert value("Principals/Principal/RunLevel") == "LeastPrivilege"
    assert value("Actions/Exec/Command") == str(root / "program/runtime/python.exe")
    assert value("Actions/Exec/Arguments") == "-IB -m sau_worker.desktop _supervise"
    assert value("Settings/ExecutionTimeLimit") == "PT0S"
    assert value("Settings/StopIfGoingOnBatteries") == "false"


def test_windows_scheduler_reinstall_start_disable_and_reenable_use_one_interactive_task(tmp_path, monkeypatch):
    from sau_worker import login
    from types import SimpleNamespace
    (tmp_path / "state").mkdir()
    installed = {}
    command_log = []
    def scheduler(args, check=True):
        command_log.append(args)
        assert args[0] == "schtasks.exe"
        command = args[1]
        name = args[args.index("/tn") + 1]
        if command == "/create":
            installed[name] = ET.parse(args[args.index("/xml") + 1]).getroot()
        elif command == "/delete":
            installed.pop(name)
        elif command == "/run":
            assert name in installed
        return SimpleNamespace(returncode=0 if name in installed else 1)
    monkeypatch.setattr(login, "WINDOWS", True)
    monkeypatch.setattr(login.subprocess, "check_output", lambda *a, **kw: '"DOMAIN\\User","S-1-5-21-123"')
    monkeypatch.setattr(login, "native", scheduler)
    login.native_login(tmp_path, start=True)
    login.native_login(tmp_path, start=True)
    assert len(installed) == 1 and sum(c[1] == "/create" for c in command_log) == 1
    login.native_login(tmp_path, remove=True)
    assert not installed
    login.native_login(tmp_path, start=True)
    assert len(installed) == 1 and command_log[-1][1] == "/run"
