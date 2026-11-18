"""Keep in-process CLI tests inside a private simulated OS user profile."""
import pytest


@pytest.fixture(autouse=True)
def isolated_managed_profile_home(monkeypatch, tmp_path_factory):
    directory = None

    def user_directory():
        nonlocal directory
        if directory is None:
            directory = tmp_path_factory.mktemp("os-profile")
        return directory

    monkeypatch.setattr("utils.profile_store._user_profile_directory", user_directory)
