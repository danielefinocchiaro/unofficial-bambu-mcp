"""HTTP transport and bearer-token tests. Spec: docs/specs/http-transport.md

Each test starts the real server as a subprocess, so what is checked is what a user runs.
Waiting is on events (port accepts, or process exited), never on a fixed sleep.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

INIT = json.dumps({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "test_http", "version": "0"}},
}).encode()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(**env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("UBMCP_")}
    e.update({k: str(v) for k, v in env.items()})
    return subprocess.Popen([sys.executable, "-m", "unofficial_bambu_mcp.server"], env=e,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _wait_listening(proc, port):
    """Return True once the port accepts; False if the process exits first."""
    while proc.poll() is None:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def _post(port, token=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=INIT, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read().decode()


@pytest.fixture
def server():
    procs = []

    def go(**env):
        p = _start(**env)
        procs.append(p)
        return p
    yield go
    for p in procs:
        if p.poll() is None:
            p.terminate()
        p.communicate()


def test_request_without_token_is_401(server):
    port = _free_port()
    p = server(UBMCP_TRANSPORT="http", UBMCP_PORT=port, UBMCP_TOKEN="t")
    assert _wait_listening(p, port), f"nothing listening on port {port}; process exited {p.poll()}"
    assert _post(port)[0] == 401
    assert _post(port, "wrong")[0] == 401


def test_request_with_token_initializes(server):
    port = _free_port()
    p = server(UBMCP_TRANSPORT="http", UBMCP_PORT=port, UBMCP_TOKEN="t")
    assert _wait_listening(p, port), f"nothing listening on port {port}; process exited {p.poll()}"
    status, body = _post(port, "t")
    assert status == 200, body
    assert "unofficial-bambu-mcp" in body


def test_open_bind_without_token_refuses_to_start(server):
    p = server(UBMCP_TRANSPORT="http", UBMCP_HOST="0.0.0.0", UBMCP_PORT=_free_port())
    p.wait()
    assert p.returncode == 2, f"exit {p.returncode}, wanted 2"


def test_unknown_transport_refuses_to_start(server):
    p = server(UBMCP_TRANSPORT="bogus")
    p.wait()
    assert p.returncode == 2, f"exit {p.returncode}, wanted 2"
