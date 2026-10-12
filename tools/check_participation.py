"""Qualify the resident game through the native runner, including private-seat commands."""

import argparse
import json
import secrets
import subprocess
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args()
    token = secrets.token_hex(32)
    name = "webdip-participation-" + uuid.uuid4().hex[:10]
    container = docker(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        "owner=webdip-participation-qualification",
        "--platform",
        "linux/amd64",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "1g",
        "--cpus",
        "2",
        "-p",
        "127.0.0.1::8080",
        "-e",
        "RUNNER_TOKEN=" + token,
        "-e",
        "WORLD_RUNTIME=webdiplomacy",
        "-e",
        'WORLD_COMMAND=["/opt/.venv/bin/python","/opt/conductor-host.py"]',
        args.image,
    )
    boot = None
    try:
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        origin = f"http://127.0.0.1:{port}"

        def call(path, value=None, method=None):
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
            if boot:
                headers["x-runner-boot"] = boot
            request = Request(
                origin + path,
                data=json.dumps(value).encode() if value is not None else None,
                headers=headers,
                method=method,
            )
            with urlopen(request, timeout=12) as response:
                return json.load(response)

        def wait(read, description):
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                try:
                    value = read()
                    if value:
                        return value
                except (HTTPError, URLError, TimeoutError, ConnectionError):
                    pass
                time.sleep(0.25)
            raise AssertionError("Timed out: " + description)

        boot = wait(lambda: call("/health"), "runner")["bootId"]
        attempt = secrets.token_hex(32)
        path = "/attempts/" + attempt
        call(
            path,
            {
                "protocol": 1,
                "id": attempt,
                "runId": attempt,
                "runtime": "webdiplomacy",
                "deadlineAt": int(time.time() * 1000) + 180_000,
                "seed": 0,
                "policies": [],
                "seats": [f"seat-{i}" for i in range(7)],
                "config": {"phase_minutes": 1, "retreat_build_minutes": 1, "press": "Regular", "end_year": 1901},
            },
            "PUT",
        )

        def control(operation, slot=0, **fields):
            return call(path + "/participation", {"operation": operation, "seat": f"seat-{slot}", **fields})

        first = wait(lambda: control("observe")["snapshot"], "game observation")
        assert first["window"], "game did not open an input window"
        observations = [control("observe", slot)["snapshot"] for slot in range(7)]
        assert len({item["observation"]["countryId"] for item in observations}) == 7
        for slot in range(7):
            control("bind", slot, controller={"id": "human", "generation": 1, "expiresAt": None})

        def submit(slot, kind, value, command_id=None, **overrides):
            command = {
                "id": command_id or uuid.uuid4().hex,
                "controllerId": "human",
                "generation": 1,
                "windowId": first["window"]["id"],
                "kind": kind,
                "value": value,
                **overrides,
            }
            return command, control("command", slot, command=command)["receipt"]

        message = "private-qualification-" + uuid.uuid4().hex
        recipient = observations[1]["observation"]["countryId"]
        command, receipt = submit(0, "press", {"toCountryID": recipient, "message": message})
        assert receipt["status"] == "applied", receipt
        assert control("command", command=command)["receipt"] == receipt
        assert control("receipt", commandId=command["id"])["receipt"] == receipt
        for slot in range(7):
            observed = control("observe", slot)["snapshot"]
            encoded = json.dumps(observed)
            assert (message in encoded) == (slot in (0, 1)), "private press crossed seat boundary"
            assert encoded.count(message) <= 1, "duplicate press after retry"
            assert "apiKey" not in encoded and "sseAuthToken" not in encoded

        _, receipt = submit(0, "orders", {"orders": [], "ready": False}, windowId="closed-window")
        assert receipt.get("code") == "window_closed", receipt
        control("bind", controller={"id": "replacement", "generation": 2, "expiresAt": None})
        _, receipt = submit(0, "orders", {"orders": [], "ready": False})
        assert receipt.get("code") == "controller_replaced", receipt
        for slot, observation in enumerate(observations):
            orders = [{"type": "Hold", "terrID": order["terrID"]} for order in observation["observation"]["orders"]]
            overrides = {"controllerId": "replacement", "generation": 2} if slot == 0 else {}
            _, receipt = submit(slot, "orders", {"orders": orders, "ready": True}, **overrides)
            assert receipt["status"] == "applied", receipt
        advanced = wait(
            lambda: (
                item
                if (item := control("observe")["snapshot"])["window"] and item["window"]["id"] != first["window"]["id"]
                else None
            ),
            "upstream adjudication",
        )
        assert advanced["revision"] > first["revision"]
        print(
            "Qualified: seven private seats, press deduplication, controller fence, "
            "stale windows, orders, upstream adjudication."
        )
    finally:
        subprocess.run(["docker", "stop", "--time", "10", container], check=False, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
