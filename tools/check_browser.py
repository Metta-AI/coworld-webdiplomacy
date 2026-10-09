"""Real Chromium turns, directly and through a constrained sandboxed play proxy."""

import argparse
import json
import secrets
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from playwright.sync_api import expect, sync_playwright
from websockets.sync.client import connect

from players.api import WebDiplomacy, holds
from tools.check_boot import docker
from tools.check_browser_boundaries import check_boundaries
from tools.check_episode import wait_for
from tools.play_proxy import PREFIX, SANDBOX


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def click_map(page, frame, selector):
    # Units are drawn with pointer-events:none; human clicks land on the province below.
    box = frame.locator(selector).bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def run_case(image, mode):
    directory = Path("tmp") / ("p3-" + mode + "-" + secrets.token_hex(3))
    directory.mkdir(parents=True)
    # Game root has no CAP_DAC_OVERRIDE; it can write here only if the mode allows it.
    directory.chmod(0o777)
    shots = Path("tmp/p3-shots")
    shots.mkdir(exist_ok=True)
    tokens = [secrets.token_hex(24) for _ in range(7)]
    tokens[0] = "seat&" + tokens[0]
    config = {
        "tokens": tokens,
        "seed": 17,
        "press": "Regular",
        "end_year": 2000,
        "phase_minutes": 59,
        "retreat_build_minutes": 59,
        "player_connect_timeout_seconds": 2,
        "episode_budget_seconds": 180,
        "completion_timeout_seconds": 3,
    }
    (directory / "config.json").write_text(json.dumps(config))
    container = docker(
        "run",
        "-d",
        "--platform",
        "linux/amd64",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "-p",
        "127.0.0.1::8080",
        "--mount",
        f"type=bind,src={directory.resolve()},dst=/artifacts",
        "-e",
        "COGAME_CONFIG_URI=file:///artifacts/config.json",
        "-e",
        "COGAME_RESULTS_URI=file:///artifacts/results.json",
        "-e",
        "COGAME_SAVE_REPLAY_URI=file:///artifacts/replay.json",
        image,
    )
    proxy = None
    evidence = {"mode": mode}
    try:
        port = docker("port", container, "8080/tcp").rsplit(":", 1)[1]
        base = "http://127.0.0.1:" + port

        def healthy():
            try:
                return urlopen(base + "/healthz", timeout=0.5).status == 200
            except OSError:
                return False

        wait_for(healthy)
        with ExitStack() as stack, sync_playwright() as playwright:
            clients = {}
            for slot in range(1, 7):
                ws = stack.enter_context(
                    connect(
                        base.replace("http", "ws")
                        + "/player?"
                        + urlencode(
                            {
                                "slot": slot,
                                "token": tokens[slot],
                            }
                        ),
                        ping_timeout=None,
                    )
                )
                hello = json.loads(ws.recv())
                country = hello["webdip"]["country_id"]
                clients[country] = WebDiplomacy(base, tokens[slot], 1, country)
            human = WebDiplomacy(base, tokens[0], 1, 6)
            wait_for(lambda: human.context()["game"]["phase"] == "Diplomacy")
            # Only the other six seats use API actions. The human's actions below are mouse/keyboard input.
            for client in clients.values():
                seat_context = client.context()
                client.orders(seat_context, holds(seat_context))
            query = {"slot": 0, "token": tokens[0]}
            if mode == "proxy":
                proxy_port = free_port()
                query["token"] = secrets.token_hex(24)
                participant_file = directory / "participant.json"
                participant_file.write_text(
                    json.dumps(
                        {
                            "slot": 0,
                            "viewer_token": query["token"],
                            "runtime_token": tokens[0],
                        }
                    )
                )
                log = stack.enter_context((directory / "proxy.log").open("w"))
                proxy = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "tools.play_proxy",
                        "--upstream",
                        base,
                        "--port",
                        str(proxy_port),
                        "--participant-file",
                        str(participant_file),
                    ],
                    stdout=log,
                    stderr=log,
                )
                proxy_base = f"http://127.0.0.1:{proxy_port}"

                def proxy_ready():
                    try:
                        return urlopen(proxy_base + "/audit", timeout=0.5).status == 200
                    except OSError:
                        return False

                wait_for(proxy_ready)
                address = proxy_base.replace("http", "ws") + PREFIX + "/player?" + urlencode(query)
                target = f"http://localhost:{proxy_port}/frame?" + urlencode({**query, "address": address})
                for path, method, expected in (
                    ("api.php", "GET", 404),
                    ("client/player", "POST", 405),
                    ("events", "GET", 404),
                    ("cache/games/0/1/game.json", "GET", 404),
                ):
                    try:
                        urlopen(Request(proxy_base + PREFIX + "/" + path, method=method))
                        raise AssertionError("proxy accepted forbidden route")
                    except HTTPError as error:
                        assert error.code == expected
            else:
                target = base + "/client/player?" + urlencode(query)
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1040 if mode == "proxy" else 1000, "height": 900})
            context.add_init_script("""const NativeWebSocket = window.WebSocket;
                window.WebSocket = class extends NativeWebSocket {
                    constructor(...args) { super(...args); window.testSeatSocket = this; }
                };""")
            page = context.new_page()
            errors, requests, messages, console = [], [], [], []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "request",
                lambda request: requests.append(
                    {
                        "method": request.method,
                        "path": urlsplit(request.url).path,
                        "origin": urlsplit(request.url).netloc,
                    }
                ),
            )
            page.on("console", lambda message: console.append(message.text))
            page.on("websocket", lambda ws: ws.on("framereceived", lambda data: messages.append(json.loads(data))))
            started = time.monotonic()
            page.goto(target)
            wrapper = page.frame_locator("iframe") if mode == "proxy" else page
            frame = wrapper.frame_locator("#board")
            if mode == "proxy":
                assert page.locator("iframe").get_attribute("sandbox") == SANDBOX
            frame.locator("#ANKARA-unit").wait_for()
            expect(frame.get_by_text("Spring 1901 Movement. Turkey, enter your orders.")).to_be_visible()
            evidence["board_load_seconds"] = round(time.monotonic() - started, 3)
            page.screenshot(path=str(shots / f"{mode}-help.png"))
            # Help occupies its own row, above every country's map, even on narrow screens.
            for width in (500, 1000):
                page.set_viewport_size({"width": width, "height": 900})
                assert wrapper.locator("#play-help").evaluate(
                    "el => el.getBoundingClientRect().bottom <= "
                    "document.querySelector('#root').getBoundingClientRect().top"
                )
                page.screenshot(path=str(shots / f"{mode}-help-{width}.png"))
            page.set_viewport_size({"width": 1040 if mode == "proxy" else 1000, "height": 900})
            wrapper.get_by_role("button", name="Dismiss help").click()
            page.reload()
            frame.locator("#ANKARA-unit").wait_for()
            expect(wrapper.locator("#play-help")).to_be_hidden()
            wrapper.get_by_role("button", name="How to play here", exact=True).click()
            expect(wrapper.locator("#play-help")).to_be_visible()
            wrapper.get_by_role("button", name="Dismiss help").click()
            page.screenshot(path=str(shots / f"{mode}-board.png"))
            hello = next(message for message in messages if message.get("type") == "hello")
            assert "api_key" not in hello["webdip"]
            if mode == "proxy":
                assert tokens[0] not in json.dumps(messages)
            click_map(page, frame, "#ANKARA-unit")
            frame.get_by_text("Move", exact=True).click()
            click_map(page, frame, "#BLACK_SEA-province")
            click_map(page, frame, "#CONSTANTINOPLE-unit")
            frame.get_by_text("Hold", exact=True).click()
            click_map(page, frame, "#SMYRNA-unit")
            frame.get_by_text("Support", exact=True).click()
            click_map(page, frame, "#CONSTANTINOPLE-unit")
            click_map(page, frame, "#CONSTANTINOPLE-unit")

            def saved():
                orders = human.context()["orders"]["orders"]
                return orders if {order["type"] for order in orders} == {"Move", "Hold", "Support hold"} else None

            evidence["saved_orders"] = wait_for(saved)
            page.wait_for_timeout(400)  # Let the board finish its visible transitions before evidence capture.
            page.screenshot(path=str(shots / f"{mode}-orders.png"))
            # The board's press control has a documented keyboard shortcut.
            page.keyboard.press("p")
            frame.locator("#user-msg").fill("Public browser greeting")
            frame.locator("#user-msg").press("Enter")
            expect(frame.get_by_text("TUR: Public browser greeting", exact=True)).to_be_visible()
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / f"{mode}-public-chat.png"))
            frame.get_by_role("button", name="ENG", exact=True).click()
            frame.locator("#user-msg").fill("Private browser greeting")
            frame.locator("#user-msg").press("Enter")
            expect(frame.get_by_text("TUR: Private browser greeting", exact=True)).to_be_visible()
            clients[1].request(
                "game/sendmessage",
                body={
                    "gameID": 1,
                    "countryID": 1,
                    "toCountryID": 6,
                    "message": "England replies privately",
                },
            )
            expect(frame.get_by_text("ENG: England replies privately", exact=True)).to_be_visible()
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / f"{mode}-private-chat.png"))
            assert "Private browser greeting" in json.dumps(clients[1].context()["messages"])
            assert "Private browser greeting" not in json.dumps(clients[2].context()["messages"])
            # Exit the input before using the shortcut to close press.
            frame.get_by_role("button", name="ENG", exact=True).click()
            page.keyboard.press("p")
            frame.get_by_role("button", name="Ready", exact=True).click()
            expect(frame.get_by_text("New phase", exact=True)).to_be_visible(timeout=15000)
            page.screenshot(path=str(shots / f"{mode}-phase-notice.png"))
            frame.get_by_text("New phase", exact=True).locator("../..").get_by_role("button").click()
            expect(frame.get_by_text("Autumn 1901 Movement. Turkey, enter your orders.")).to_be_visible()
            frame.locator("#BLACK_SEA-unit").wait_for()
            evidence["turn_seconds"] = round(time.monotonic() - started, 3)
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / f"{mode}-next-phase.png"))
            assert human.context()["game"]["turn"] == 1
            assert any(message.get("type") == "event" for message in messages)
            assert any("x-json" in message.get("headers", {}) for message in messages)
            # Unsupported site controls must remain in the game and explain the limitation.
            page.keyboard.press("p")
            frame.get_by_text("INFO", exact=True).click()
            frame.get_by_role("button", name="Create", exact=True).click()
            expect(frame.get_by_role("status")).to_have_text("Sandbox is not available in this game")
            frame.get_by_role("link", name="Legacy Board", exact=True).click()
            expect(frame.get_by_role("status")).to_have_text("Site navigation is not available in this game")
            evidence["authorization_rejections"] = check_boundaries(base, tokens, human.context())
            # A dropped transport reconnects; an explicit seat takeover is tested separately.
            frame.locator("body").evaluate("() => window.testSeatSocket.close()")
            expect(frame.get_by_role("status")).to_contain_text("Disconnected")
            page.screenshot(path=str(shots / f"{mode}-disconnected.png"))
            deadline = time.monotonic() + 15
            while len([m for m in messages if m.get("type") == "hello"]) < 2:
                assert time.monotonic() < deadline, "automatic reconnect did not authenticate"
                page.wait_for_timeout(100)
            expect(frame.locator("#connection-status")).to_be_empty()
            expect(frame.get_by_text("Autumn 1901 Movement. Turkey, enter your orders.")).to_be_visible()
            frame.locator("#BLACK_SEA-unit").wait_for()
            evidence["reconnect_preserved_turn"] = True
            frame.get_by_text("PRESS", exact=True).click()
            frame.get_by_role("button", name="ENG", exact=True).click()
            clients[1].request(
                "game/sendmessage", body={"gameID": 1, "countryID": 1, "toCountryID": 6, "message": "After reconnect"}
            )
            expect(frame.get_by_text("ENG: After reconnect", exact=True)).to_be_visible(timeout=10000)
            assert not errors, errors
            assert not context.cookies(), "board set cookies"
            evidence.update(
                page_errors=errors,
                requests=requests,
                upstream_analytics_blocked=any(
                    "Content Security Policy" in item and "googletagmanager" in item for item in console
                ),
            )
            if mode == "proxy":
                assert tokens[0] not in json.dumps(messages)
                evidence["proxy_requests"] = json.load(urlopen(proxy_base + "/audit"))
                assert all(
                    request["path"].startswith((PREFIX + "/client/", "/frame"))
                    or request["origin"] == "www.googletagmanager.com"
                    for request in requests
                )
            takeover_address = (
                address if mode == "proxy" else base.replace("http", "ws") + "/player?" + urlencode(query)
            )
            with connect(takeover_address) as takeover:
                assert json.loads(takeover.recv(timeout=5))["type"] == "hello"
                expect(frame.get_by_role("status")).to_contain_text("Seat opened by another controller")
                page.wait_for_timeout(1200)  # Beyond the first automatic reconnect delay.
                assert takeover.ping().wait(timeout=2), "browser took the seat back"
                assert sum(message.get("type") == "seat_replaced" for message in messages) == 1
            evidence["takeover_stops_reconnect"] = True
            invalid = context.new_page()
            # An invalid seat exercises wrapper help without starting upstream React,
            # whose own storage dependencies are outside this wrapper's contract.
            invalid.add_init_script("""Object.defineProperty(window, 'localStorage', {
                get() { throw new DOMException('Storage blocked', 'SecurityError'); }
            });""")
            invalid_base = proxy_base + PREFIX if mode == "proxy" else base
            invalid.goto(invalid_base + "/client/player?slot=0&token=invalid")
            expect(invalid.locator("#play-help")).to_be_visible()
            invalid.get_by_role("button", name="Dismiss help").click()
            expect(invalid.locator("#play-help")).to_be_hidden()
            invalid.get_by_role("button", name="How to play here", exact=True).click()
            expect(invalid.locator("#play-help")).to_be_visible()
            expect(invalid.frame_locator("#board").get_by_role("status")).to_contain_text("Check your seat link")
            invalid.screenshot(path=str(shots / f"{mode}-invalid-seat.png"))
            expect(invalid.frame_locator("#board").get_by_role("status")).to_contain_text(
                "Automatic reconnect stopped", timeout=45000
            )
            evidence["bounded_retries"] = True
            browser.close()
        evidence["passed"] = True
        (directory / "evidence.json").write_text(json.dumps(evidence, indent=2))
        print(
            json.dumps(
                {
                    "case": mode,
                    "passed": True,
                    "board_load_seconds": evidence["board_load_seconds"],
                    "turn_seconds": evidence["turn_seconds"],
                    "evidence": str(directory),
                }
            ),
            flush=True,
        )
    finally:
        if proxy:
            proxy.terminate()
            proxy.wait(timeout=10)
        docker("stop", "--time", "45", container)
        (directory / "game.log").write_text(docker("logs", container))
        (directory / "container-state.json").write_text(docker("inspect", "--format", "{{json .State}}", container))
        docker("rm", container)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("cases", nargs="*", help="direct, proxy (default: both)")
    args = parser.parse_args()
    if set(args.cases) - {"direct", "proxy"}:
        parser.error("cases must be direct or proxy")
    for case in args.cases or ["direct", "proxy"]:
        run_case(args.image, case)
