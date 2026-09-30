"""Build-time database installation and runtime service supervision."""

import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from adapter.supervisor import RUN, Supervisor

APP = Path("/application")
CONFIG = Path("/opt/config")


def sql(statement):
    return subprocess.run(
        ["mariadb", "--defaults-file=/opt/config/mariadb.cnf", "--batch", "--skip-column-names"],
        input=statement,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def prepare():
    os.umask(0o077)
    for path in (RUN / "logs", Path("/run/mysqld"), APP / "cache", APP / "variants/Classic/cache"):
        path.mkdir(parents=True, exist_ok=True)
    settings = {
        name: secrets.token_hex(32) for name in ("salt", "secret", "gameMasterSecret", "jsonSecret", "sseSecret")
    }
    settings.update(
        database_socket="127.0.0.1",
        database_username="webdiplomacy",
        database_password=secrets.token_hex(32),
        database_name="webdiplomacy",
        redisHost="127.0.0.1",
    )
    (RUN / "settings.json").write_text(json.dumps(settings))
    sample = (APP / "config.sample.php").read_text()
    old = "public static function errorlogDirectory()\n\t{\n\t\treturn false;"
    if old not in sample:
        raise RuntimeError("upstream error log configuration changed")
    sample = sample.replace(old, "public static function errorlogDirectory()\n\t{\n\t\treturn '/run/webdip/logs';", 1)
    (APP / "config.php").write_text(sample + "\n" + (CONFIG / "webdip.php").read_text())
    env = dict(
        SSE_PORT="/run/webdip/sse.sock",
        SSE_SECRET=settings["sseSecret"],
        REDIS_HOST="127.0.0.1",
        GAMEMASTER_URL="http://127.0.0.1:8080/gamemaster.php",
        GAMEMASTER_SECRET=settings["gameMasterSecret"],
    )
    (APP / "sse-server/.env").write_text("".join(f"{key}={value}\n" for key, value in env.items()))
    return settings


def command_ready(command):
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def tcp_ready(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def api_ready():
    try:
        with urlopen("http://127.0.0.1:8080/api.php", timeout=0.5):
            return False
    except HTTPError as error:
        return error.code == 400 and error.read().strip() == b"No route provided."
    except (URLError, TimeoutError):
        return False


def start_storage(supervisor):
    supervisor.start("redis", ["redis-server", "/opt/config/redis.conf"])
    supervisor.start("mariadb", ["mariadbd", "--defaults-file=/opt/config/mariadb.cnf"])
    supervisor.wait_for(
        lambda: command_ready(["mariadb-admin", "--defaults-file=/opt/config/mariadb.cnf", "ping", "--silent"]),
        "mariadb",
    )
    supervisor.wait_for(lambda: command_ready(["redis-cli", "ping"]), "redis")


def bake(supervisor, settings):
    sql(
        "CREATE DATABASE webdiplomacy; CREATE USER 'webdiplomacy'@'127.0.0.1' IDENTIFIED BY '"
        + settings["database_password"]
        + "'; GRANT ALL ON webdiplomacy.* TO 'webdiplomacy'@'127.0.0.1';"
    )
    sql("USE webdiplomacy;\n" + (APP / "install/FullInstall/fullInstall.sql").read_text())
    output = subprocess.run(["php", "/opt/php/wdc_install.php"], capture_output=True, text=True, check=True)
    result = json.loads(output.stdout)
    if result != {"installed": True, "version": 183, "countries": 7}:
        raise RuntimeError("database bake validation failed")
    if sql("SELECT countryCount FROM webdiplomacy.wD_VariantInfo WHERE variantID=1") != "7":
        raise RuntimeError("Classic metadata missing")
    print(json.dumps(result), flush=True)
    # The image contains no usable application password; each boot rotates it.
    sql("ALTER USER 'webdiplomacy'@'127.0.0.1' IDENTIFIED BY '' ACCOUNT LOCK;")


def main():
    if os.environ.get("COGAME_LOAD_REPLAY_URI"):
        os.execv(sys.executable, [sys.executable, "/opt/adapter/server.py"])
    supervisor = Supervisor()
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: supervisor.stopping.set())
    server = None
    thread = None
    status = 0
    try:
        settings = prepare()
        start_storage(supervisor)
        if "--bake" in sys.argv:
            bake(supervisor, settings)
        else:
            sql(
                "ALTER USER 'webdiplomacy'@'127.0.0.1' IDENTIFIED BY '"
                + settings["database_password"]
                + "' ACCOUNT UNLOCK; "
                "UPDATE webdiplomacy.wD_Misc SET value=UNIX_TIMESTAMP() WHERE name='LastProcessTime';"
            )
            app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

            @app.get("/healthz")
            def health():
                ready = supervisor.ready and all(child.poll() is None for _, child in supervisor.children)
                return JSONResponse({"status": "ok" if ready else "starting"}, status_code=200 if ready else 503)

            server = uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=8082, access_log=False, log_level="warning", ws="websockets")
            )
            thread = threading.Thread(target=server.run, name="health-server")
            thread.start()
            supervisor.start(
                "php-fpm", ["php-fpm8.4", "--allow-to-run-as-root", "--fpm-config", "/opt/config/php-fpm.conf"]
            )
            supervisor.wait_for(lambda: tcp_ready(9000), "php-fpm")
            supervisor.start("nginx", ["nginx", "-c", "/opt/config/nginx.conf"])
            supervisor.wait_for(api_ready, "webDiplomacy API")
            supervisor.start("sse", ["node", "server.js"], cwd=APP / "sse-server")
            supervisor.wait_for(lambda: (RUN / "sse.sock").exists(), "sse")
            supervisor.ready = True
            print("webDiplomacy services ready", flush=True)
            while not supervisor.stopping.wait(0.1):
                supervisor.check()
                if not thread.is_alive():
                    raise RuntimeError("health server exited")
    except InterruptedError:
        pass
    except Exception as error:
        # Exception details from PHP/SQL may contain credentials. Keep them private.
        (RUN / "logs/boot-error.log").write_text(repr(error))
        print("webDiplomacy boot or service failure; see private boot log", flush=True)
        status = 1
    finally:
        if server:
            server.should_exit = True
        try:
            supervisor.shutdown()
        except RuntimeError:
            status = 1
        if thread:
            thread.join(timeout=10)
            if thread.is_alive():
                status = 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
