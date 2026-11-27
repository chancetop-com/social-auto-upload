"""The private worker verifies the release by asking its absolute paired entry."""
import subprocess


def test_paired_cli_identifies_its_installed_release(install_cli, tmp_path):
    executable, _ = install_cli(tmp_path / "paired release")
    result = subprocess.run([executable, "--version"], cwd=tmp_path, capture_output=True, text=True)
    assert (result.returncode, result.stdout.strip()) == (0, "sau 0.1.0")
