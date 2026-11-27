"""Verify the released Linux entrypoint over HTTP and a loopback TLS terminator."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
import ssl
import subprocess
from threading import Thread
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
import pytest


@contextmanager
def tls_ingress(port, tmp):
    cert, key = tmp / 'loopback.crt', tmp / 'loopback.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                    '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1',
                    '-keyout', key, '-out', cert], check=True, capture_output=True)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            connection = HTTPConnection('127.0.0.1', port, timeout=8)
            try:
                body = self.rfile.read(int(self.headers['Content-Length']))
                connection.request('POST', self.path, body, dict(self.headers))
                response = connection.getresponse()
                self.send_response(response.status)
                self.end_headers()
                self.wfile.write(response.read())
            finally:
                connection.close()

        def log_message(self, *args):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f'https://127.0.0.1:{server.server_port}',
                              verify=ssl.create_default_context(cafile=cert), trust_env=False) as client:
                yield client
        finally:
            server.shutdown()
            thread.join()


@pytest.fixture
def image_fixture():
    image = os.environ.get('GATEWAY_TEST_IMAGE')
    if not image:
        pytest.skip('set GATEWAY_TEST_IMAGE to run the built-image test')
    admin = os.environ['GATEWAY_TEST_DATABASE_URL']
    container = 'gateway-test-' + uuid4().hex
    owner = 'gateway_' + uuid4().hex
    password = uuid4().hex
    docker_host = os.environ.get('GATEWAY_TEST_PG_HOST', 'host.docker.internal')
    docker_port = os.environ.get('GATEWAY_TEST_PG_PORT', conninfo_to_dict(admin).get('port', '5432'))
    dsn = make_conninfo(host=docker_host, port=docker_port, dbname=owner, user=owner, password=password)
    env = dict(os.environ, GATEWAY_DATABASE_URL=dsn, GATEWAY_DESKTOP_TOKEN='desktop-fixture',
               GATEWAY_INTERNAL_TOKEN='internal-fixture')

    def docker(*args, check=True):
        return subprocess.run(['docker', *args], env=env, capture_output=True, text=True, check=check).stdout.strip()

    args = ['-e', 'GATEWAY_DATABASE_URL', '-e', 'GATEWAY_DESKTOP_TOKEN', '-e', 'GATEWAY_INTERNAL_TOKEN']
    if os.environ.get('GATEWAY_TEST_IMAGE_REDIS_URL'):
        env.update(GATEWAY_REDIS_URL=os.environ['GATEWAY_TEST_IMAGE_REDIS_URL'],
                   GATEWAY_REDIS_CHANNEL='test:social-media-web-api:' + container)
        args.extend(['-e', 'GATEWAY_REDIS_URL', '-e', 'GATEWAY_REDIS_CHANNEL'])
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(owner), sql.Literal(password)))
        try:
            conn.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(owner), sql.Identifier(owner)))
            assert docker('image', 'inspect', '-f', '{{.Os}}/{{.Architecture}}', image) == 'linux/amd64'
            for _ in range(2):
                docker('run', '--rm', *args, image, 'migrate')
            docker('run', '-d', '--name', container, '-p', '127.0.0.1::8080', *args, image)
            yield docker, container
        finally:
            docker('rm', '-f', container, check=False)
            conn.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(owner)))
            conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(owner)))


def ready_client(docker, name):
    port = int(docker('port', name, '8080/tcp').rsplit(':', 1)[1])
    client = httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=8)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            if client.get('/health-check').json() == {'status': 'ready'}:
                return port, client
        except (httpx.TransportError, ValueError):
            pass
        time.sleep(0.1)
    client.close()
    pytest.fail('packaged service did not become ready')


def test_packaged_check_disconnect_and_shutdown(image_fixture, tmp_path):
    docker, name = image_fixture
    desktop = {'Authorization': 'Bearer desktop-fixture'}
    internal = {'Authorization': 'Bearer internal-fixture'}
    session = str(uuid4())
    report = {'sessionId': session, 'mode': 'self-check', 'release': '0.1.0', 'contractVersion': 1,
              'capacity': 1, 'freeSlots': 1, 'capabilities': [], 'providers': []}
    target = {'provider': 'bitbrowser', 'profileId': 'test-window', 'platform': 'tiktok'}
    claim = {'sessionId': session, 'waitSeconds': 1}
    receipt = {'cloudConnected': True, 'profileVisible': False, 'cliInvoked': False,
               'platformLogin': 'unknown', 'exitCode': None}
    port, client = ready_client(docker, name)
    with closing(client), tls_ingress(port, tmp_path) as tls:
        tls.post('/session', json=report, headers=desktop).raise_for_status()
        start = time.monotonic()
        assert tls.post('/publish-task/claim', json=claim, headers=desktop).json() == {'task': None}
        assert time.monotonic() - start >= 0.9
        payload = httpx.Request('POST', '/', json={**claim, 'waitSeconds': 30}).content
        with socket.create_connection(('127.0.0.1', port)) as abandoned:
            abandoned.sendall(b'POST /publish-task/claim HTTP/1.1\r\nHost: localhost\r\n'
                              b'Authorization: Bearer desktop-fixture\r\nContent-Type: application/json\r\n'
                              + f'Content-Length: {len(payload)}\r\n\r\n'.encode() + payload)
            time.sleep(0.3)
        time.sleep(1)
        record = tls.post(f'/session/{session}/self-check', json=target, headers=desktop).json()
        lookup = '/internal/occurrences/' + record['workflowId']
        time.sleep(1)
        assert client.get(lookup, headers=internal).json()['state'] == 'pending'
        assert tls.post('/publish-task/claim', json=claim, headers=desktop).json()['task']['workflowId'] == record['workflowId']
        result = {'sessionId': session, 'workflowId': record['workflowId'], 'receipt': receipt}
        stored = tls.post('/publish-task/result', json=result, headers=desktop).json()
        assert stored['receipt'] == receipt
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(client.post, '/publish-task/claim', json={**claim, 'waitSeconds': 30}, headers=desktop)
            time.sleep(0.5)
            stop = pool.submit(docker, 'stop', '--time', '10', name)
            assert pending.result(timeout=5).json() == {'task': None}
            stop.result(timeout=10)
        assert docker('inspect', '-f', '{{.State.ExitCode}}', name) in {'0', '143'}
        docker('start', name)
        _, restarted = ready_client(docker, name)
        with closing(restarted):
            assert restarted.get(lookup, headers=internal).json() == stored
