"""Run upstream compose core using an isolated Docker volume, never a writable checkout."""

import json
import os
import subprocess
from pathlib import Path


class StockStack:
    def __init__(self, directory):
        self.directory = directory.resolve()
        self.project = directory.name
        self.volume = self.project + "-source"
        self.file = self.directory / "stock-compose.json"

    def compose(self, *args, **kwargs):
        return subprocess.run(
            ["docker", "compose", "-p", self.project, "-f", str(self.file), "--profile", "core", *args],
            check=True,
            **kwargs,
        )

    def start(self):
        source = Path("webdiplomacy").resolve()
        config = json.loads(
            subprocess.check_output(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(source / "docker-compose.yml"),
                    "--profile",
                    "core",
                    "config",
                    "--format",
                    "json",
                ],
            )
        )
        config.pop("name", None)
        config["networks"] = {"default": {}}
        if subnet := os.environ.get("WEBDIP_STOCK_SUBNET"):
            config["networks"]["default"]["ipam"] = {"config": [{"subnet": subnet}]}
        config["volumes"] = {"source": {"external": True, "name": self.volume}}
        config["services"] = {
            name: service for name, service in config["services"].items() if "core" in service["profiles"]
        }
        for name, service in config["services"].items():
            service.pop("container_name", None)
            service["platform"] = "linux/amd64"
            for port in service.get("ports", []):
                port["published"] = "0"
            service["networks"] = {"default": {"aliases": ["webdiplomacy-db"] if name == "mariadb" else []}}
            for volume in service.get("volumes", []):
                if volume["source"] in (str(source), str(source / "sse-server")):
                    volume.clear()
                    volume.update(type="volume", source="source", target="/application")
                else:
                    volume["read_only"] = True
            if name == "sse":
                service["working_dir"] = "/application/sse-server"
            if name == "mariadb":
                service["command"] = ["--innodb-buffer-pool-size=128M"]
        self.file.write_text(json.dumps(config, indent=2))
        subprocess.run(["docker", "volume", "create", self.volume], check=True, stdout=subprocess.DEVNULL)
        archive = subprocess.Popen(["git", "-C", str(source), "archive", "HEAD"], stdout=subprocess.PIPE)
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--platform",
                    "linux/amd64",
                    "-i",
                    "-v",
                    self.volume + ":/stock",
                    "--entrypoint",
                    "sh",
                    "coworld-webdiplomacy-game:latest",
                    "-c",
                    "tar -xf - -C /stock && chown -R 1000:1000 /stock",
                ],
                stdin=archive.stdout,
                check=True,
            )
        finally:
            archive.stdout.close()
            assert archive.wait() == 0
        with (self.directory / "stock-build.log").open("w") as log:
            self.compose("up", "-d", "--build", stdout=log, stderr=subprocess.STDOUT)

    def prepare(self):
        from tools.check_episode import wait_for

        def ready():
            result = self.compose(
                "exec", "-T", "php-fpm", "cat", "/application/gamemaster-entrypoint.txt", capture_output=True, text=True
            )
            return "READY -" in result.stdout

        wait_for(ready, timeout=180)
        # Stock nginx may start before its SSE DNS name exists. Retry startup after core is present.
        self.compose("restart", "webserver", capture_output=True)
        self.compose("cp", "php", "php-fpm:/opt/php", capture_output=True)
        self.compose("cp", "tools/stock_prepare.php", "php-fpm:/opt/stock_prepare.php", capture_output=True)
        result = self.compose(
            "exec",
            "-T",
            "--user",
            "www-data",
            "php-fpm",
            "php",
            "/opt/php/wdc_install.php",
            capture_output=True,
            text=True,
        )
        (self.directory / "fixture-install.log").write_text(result.stdout + result.stderr)

    def create(self, config):
        self.compose("exec", "-T", "php-fpm", "php", "/opt/stock_prepare.php", capture_output=True)
        result = self.compose(
            "exec",
            "-T",
            "--user",
            "www-data",
            "php-fpm",
            "php",
            "/opt/php/wdc_create_game.php",
            input=json.dumps(config),
            capture_output=True,
            text=True,
        )
        (self.directory / "fixture-create.log").write_text(result.stdout + result.stderr)
        created = json.loads(result.stdout)
        self.compose(
            "exec",
            "-T",
            "--user",
            "www-data",
            "php-fpm",
            "php",
            "/opt/php/wdc_start.php",
            str(created["game_id"]),
            capture_output=True,
        )
        port = self.compose("port", "webserver", "80", capture_output=True, text=True).stdout.strip().rsplit(":", 1)[1]
        from players.api import WebDiplomacy

        return {
            seat["country_id"]: WebDiplomacy(
                "http://127.0.0.1:" + port, config["tokens"][seat["slot"]], created["game_id"], seat["country_id"]
            )
            for seat in created["seats"]
        }

    def close(self):
        self.compose("down", "--timeout", "2", "--volumes", "--remove-orphans", stdout=subprocess.DEVNULL)
        subprocess.run(["docker", "volume", "rm", self.volume], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    directory = Path("tmp/p4-stock")
    directory.mkdir(exist_ok=True)
    StockStack(directory).start()
