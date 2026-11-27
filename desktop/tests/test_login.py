import plistlib
import subprocess
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
