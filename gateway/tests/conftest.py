import os
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
from fastapi.testclient import TestClient

from sau_gateway.app import create_app
from sau_gateway.database import migrate


@pytest.fixture
def gateway_env(monkeypatch):
    root = os.environ.get("GATEWAY_TEST_DATABASE_URL")
    if not root:
        pytest.skip("set GATEWAY_TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema = "fixture_" + uuid4().hex
    with psycopg.connect(root, autocommit=True) as conn:
        conn.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    try:
        dsn = make_conninfo(root, options="-c search_path=" + schema)
        monkeypatch.setenv("GATEWAY_DATABASE_URL", dsn)
        monkeypatch.setenv("GATEWAY_INTERNAL_TOKEN", "fixture-internal")
        monkeypatch.setenv("GATEWAY_DESKTOP_TOKEN", "fixture-desktop")
        migrate(dsn)
        migrate(dsn)
        yield dsn
    finally:
        with psycopg.connect(root, autocommit=True) as conn:
            conn.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


@pytest.fixture
def gateway(gateway_env):
    with TestClient(create_app()) as client:
        yield client
