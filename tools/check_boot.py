"""Exercise the image with the capability restrictions used by hosted games."""

import argparse
import json
import subprocess
import time
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def response(url):
    try:
        with urlopen(url, timeout=0.5) as reply:
            return reply.status, reply.read().decode()
    except HTTPError as error:
        return error.code, error.read().decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--crash-service", action="store_true")
    parser.add_argument("--unavailable-dns", action="store_true", help="Check startup with an unreachable DNS resolver")
    args = parser.parse_args()
    dns_options = (
        ["--dns", "192.0.2.1", "--dns-search", "startup.invalid", "--dns-option", "ndots:5"]
        if args.unavailable_dns
        else []
    )
    container = docker(
        "create",
        "--platform",
        "linux/amd64",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "-p",
        "127.0.0.1::8080",
        *dns_options,
        args.image,
    )
    try:
        started = time.monotonic()
        docker("start", container)
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        base = f"http://127.0.0.1:{port}"
        while True:
            try:
                code, body = response(base + "/healthz")
                if code == 200:
                    assert json.loads(body) == {"status": "ok"}, body
                    break
            except (URLError, TimeoutError, ConnectionError, RemoteDisconnected):
                pass
            assert time.monotonic() - started < 10, "health was not ready within 10 seconds"
            assert docker("inspect", "-f", "{{.State.Running}}", container) == "true", "container exited"
            time.sleep(0.05)
        elapsed = time.monotonic() - started
        assert elapsed < 10, elapsed
        print(f"healthy in {elapsed:.2f}s")
        code, body = response(base + "/api.php")
        print(f"API HTTP {code}: {body[:160]}")
        assert code == 400 and body.strip() == "No route provided.", body
        assert response(base + "/events")[0] == 403
        for path in ("/config.php", "/sse-server/.env", "/install/index.php", "/gamemaster.php"):
            assert response(base + path)[0] in (403, 404), path
        audit = """from pathlib import Path
count = 0
for path in Path('/proc').glob('[0-9]*/status'):
    try:
        values = dict(line.split(':', 1) for line in path.read_text().splitlines() if ':' in line)
    except FileNotFoundError:
        continue
    assert set(values['Uid'].split()) == {'0'}, values['Name']
    assert set(values['Gid'].split()) == {'0'}, values['Name']
    for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
        assert int(values[key], 16) == 0, (values['Name'], key)
    assert values['NoNewPrivs'].strip() == '1', values['Name']
    count += 1
print(f'{count} processes: root, zero capabilities, no-new-privileges')
listeners = {}
for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
    fields = line.split()
    if fields[3] == '0A':
        address, port = fields[1].split(':')
        listeners[int(port, 16)] = address
expected = {8080: '00000000', 8082: '0100007F', 3306: '0100007F', 6379: '0100007F', 9000: '0100007F'}
assert listeners == expected, listeners
import json
settings = json.loads(Path('/run/webdip/settings.json').read_text())
for name in ('salt', 'secret', 'gameMasterSecret', 'jsonSecret', 'sseSecret', 'database_password'):
    assert len(settings[name]) == 64, name
assert Path('/run/webdip/settings.json').stat().st_mode & 0o777 == 0o600
print('private service binds and fresh 0600 secrets verified')
"""
        print(docker("exec", container, "/opt/.venv/bin/python", "-c", audit))
        # Let the upstream loop complete multiple calls, then verify its DB heartbeat.
        before = docker(
            "exec",
            container,
            "mariadb",
            "--defaults-file=/opt/config/mariadb.cnf",
            "-Nse",
            "SELECT value FROM webdiplomacy.wD_Misc WHERE name='LastProcessTime'",
        )
        deadline = time.monotonic() + 10
        while True:
            after = docker(
                "exec",
                container,
                "mariadb",
                "--defaults-file=/opt/config/mariadb.cnf",
                "-Nse",
                "SELECT value FROM webdiplomacy.wD_Misc WHERE name='LastProcessTime'",
            )
            if int(after) > int(before):
                break
            assert time.monotonic() < deadline, "gamemaster heartbeat did not advance within 10 seconds"
            time.sleep(0.2)
        print("upstream gamemaster heartbeat advanced")
        verify_logs = (
            "from pathlib import Path; text = Path('/run/webdip/logs/sse.log').read_text(); "
            "assert 'Gamemaster call failed' not in text; print('gamemaster log: no failed calls')"
        )
        print(docker("exec", container, "/opt/.venv/bin/python", "-c", verify_logs))
        stopped = time.monotonic()
        if args.crash_service:
            docker("exec", container, "pkill", "-KILL", "-x", "node")
            expected = "1"
            event = "SSE crash"
        else:
            docker("stop", "--timeout", "45", container)
            expected = "0"
            event = "SIGTERM"
        code = docker("wait", container)
        assert code == expected, f"exit status {code}"
        print(f"{event}: exit {code} in {time.monotonic() - stopped:.2f}s")
    except Exception:
        Path("tmp").mkdir(exist_ok=True)
        subprocess.run(
            ["docker", "cp", f"{container}:/run/webdip/logs", f"tmp/boot-failure-{container[:12]}"], check=False
        )
        raise
    finally:
        docker("rm", "-f", container)


if __name__ == "__main__":
    main()
