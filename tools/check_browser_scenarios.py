"""Build, retreat, convoy and Draw through the untouched board, in both transports."""

import argparse
import json
import secrets
import subprocess
import sys
import time
from contextlib import ExitStack
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright
from websockets.sync.client import connect

from players.api import verify_orders
from players.scenarios import play, public
from tools.check_browser import click_map, free_port
from tools.check_episode import wait_for
from tools.play_proxy import PREFIX
from tools.player_fixture import game


class BoardPlayer:
    """Scenario driver whose writes are exclusively real mouse/keyboard actions."""

    def __init__(self, api, page, frame, territories, directory):
        self.api, self.page, self.frame = api, page, frame
        self.territories = territories
        self.directory = directory
        self.phase = (0, "Diplomacy")

    def __getattr__(self, name):
        return getattr(self.api, name)

    def click(self, terr, unit=False):
        name = self.territories[terr].upper().replace(" ", "_")
        click_map(self.page, self.frame, f"#{name}-{'unit' if unit else 'province'}")

    def advance_view(self, context):
        phase = (context["game"]["turn"], context["game"]["phase"])
        if phase != self.phase:
            notice = self.frame.get_by_text("New phase", exact=True)
            expect(notice).to_be_visible(timeout=15000)
            notice.locator("../..").get_by_role("button").click()
            self.phase = phase
            self.page.wait_for_timeout(300)

    def orders(self, context, submitted, ready="Yes"):
        self.advance_view(context)
        if ready == "Yes":
            self.frame.get_by_role("button", name="Ready", exact=True).click()
            return []
        for item in submitted:
            kind = item["type"]
            if kind == "Build Army":
                self.click(item["toTerrID"])
                # Paris is inland: the board selects Army immediately.
            elif kind == "Retreat":
                # The dislodged unit and invading unit share the province identifier.
                self.click(item["terrID"])
                self.click(item["toTerrID"])
            else:
                self.click(item["terrID"], unit=True)
                button = "Via Convoy" if item.get("viaConvoy") == "Yes" else kind
                self.frame.get_by_text(button, exact=True).click()
                if kind == "Convoy":
                    self.click(item["fromTerrID"])
                if kind in ("Move", "Convoy"):
                    self.click(item["toTerrID"])
        deadline = time.monotonic() + 10
        while True:
            saved = self.api.context()["orders"]["orders"]
            try:
                verify_orders(submitted, saved)
                break
            except (ValueError, TypeError):
                # Autosave may briefly expose an incomplete order with a null destination.
                assert time.monotonic() < deadline, (submitted, saved)
                self.page.wait_for_timeout(100)
        self.page.screenshot(path=str(self.directory / f"orders-{self.phase[0]}-{self.phase[1]}.png"))
        return saved

    def vote(self, vote):
        assert vote == "Draw"
        self.advance_view(self.api.context())
        self.page.keyboard.press("p")
        self.frame.get_by_text("CONTROL", exact=True).click()
        self.frame.get_by_role("button", name="Draw", exact=True).click()
        self.page.screenshot(path=str(self.directory / "draw-vote.png"))


def run(image, mode, scenario):
    with game(image, f"p5-{mode}-{scenario}") as (clients, directory, container, sockets):
        config = json.loads((directory / "config.json").read_text())
        human = clients[2]
        slot = config["tokens"].index(human.key)
        sockets[slot].close()
        sockets[slot] = None
        query = {"slot": slot, "token": human.key}
        with sync_playwright() as playwright, ExitStack() as stack:
            if mode == "proxy":
                port = free_port()
                query["token"] = secrets.token_hex(24)
                participant = directory / "participant.json"
                participant.write_text(
                    json.dumps(dict(slot=slot, runtime_token=human.key, viewer_token=query["token"]))
                )
                log = stack.enter_context((directory / "proxy.log").open("w"))
                proxy = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "tools.play_proxy",
                        "--upstream",
                        human.url,
                        "--port",
                        str(port),
                        "--participant-file",
                        str(participant),
                    ],
                    stdout=log,
                    stderr=log,
                )
                stack.callback(lambda: (proxy.terminate(), proxy.wait(timeout=10)))

                def healthy():
                    try:
                        return urlopen(f"http://127.0.0.1:{port}/audit", timeout=0.5).status == 200
                    except OSError:
                        return False

                wait_for(healthy)
                query["address"] = f"ws://127.0.0.1:{port}{PREFIX}/player?" + urlencode(query)
                target = f"http://localhost:{port}/frame?" + urlencode(query)
                spectator = f"http://localhost:{port}/frame?" + urlencode(
                    {"view": "global", "address": f"ws://127.0.0.1:{port}{PREFIX}/global"}
                )
            else:
                target = human.url + "/client/player?" + urlencode(query)
                spectator = human.url + "/client/global"
            browser = playwright.chromium.launch()
            stack.callback(browser.close)
            page = browser.new_page(viewport={"width": 1040, "height": 950})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(target)
            frame = page.frame_locator("iframe") if mode == "proxy" else page
            frame.get_by_role("button", name="Dismiss help").click()
            frame.locator("#PARIS-unit").wait_for()
            viewer = browser.new_page(viewport={"width": 1040, "height": 950})
            viewer.on("pageerror", lambda error: errors.append(str(error)))
            viewer.goto(spectator)
            view = viewer.frame_locator("iframe") if mode == "proxy" else viewer
            expect(view.locator("#connection")).to_contain_text("Live match")
            marker = "p5-private-sentinel"
            human.request("game/sendmessage", body=dict(gameID=1, countryID=2, toCountryID=1, message=marker))
            human.request(
                "game/sendmessage", body=dict(gameID=1, countryID=2, toCountryID=0, message="P5 public greeting")
            )
            expect(view.locator("#press")).to_contain_text("P5 public greeting")
            territories = {t["id"]: t["name"] for t in public(human.context(), human.url)["variant"]["territories"]}
            clients[2] = BoardPlayer(human, page, frame, territories, directory)
            public_ws = stack.enter_context(connect(human.url.replace("http:", "ws:") + "/global", ping_timeout=None))
            captured = []

            def observe(clients, contexts):
                wanted = contexts[1]["game"]
                deadline = time.monotonic() + 15
                while True:
                    snapshot = json.loads(public_ws.recv(timeout=15))
                    if (snapshot["game"]["turn"], snapshot["game"]["phase"]) == (wanted["turn"], wanted["phase"]):
                        break
                    assert time.monotonic() < deadline
                assert marker not in json.dumps(snapshot)
                assert all(token not in json.dumps(snapshot) for token in config["tokens"])
                assert snapshot["map"]["png"].startswith("data:image/png;base64,iVBOR")
                assert snapshot["episode"]["seed"] == config["seed"]
                # A write-shaped message on /global only requests a public refresh.
                public_ws.send(
                    json.dumps(
                        {
                            "type": "request",
                            "method": "POST",
                            "path": "/api.php",
                            "body": "route=game/togglevote&vote=Cancel",
                        }
                    )
                )
                captured.append(snapshot)
                expect(view.locator("#phase")).to_contain_text(
                    wanted["phase"] if wanted["phase"] != "Finished" else "Final", timeout=10000
                )
                viewer.screenshot(path=str(directory / f"public-{len(captured)}.png"))

            try:
                play(scenario, clients, observe=observe)
                assert not errors, errors
                (directory / "public-frames.json").write_text(json.dumps(captured))
            except Exception:
                page.screenshot(path=str(directory / "failure.png"))
                (directory / "failure.html").write_text(page.content())
                raise
    replay = json.loads((directory / "replay.json").read_text())
    assert marker not in json.dumps(replay)
    assert replay[-1]["ending"]["outcome"] == "drawn"
    for live in captured:
        saved = next(frame for frame in replay if frame["lifecycle"] == live["lifecycle"])
        for field in ("units", "territories"):
            assert saved["game"][field] == live["game"][field]
        assert saved["map"] == live["map"]
    assert json.loads((directory / "results.json").read_text())["seed"] == replay[-1]["episode"]["seed"]
    print(json.dumps(dict(mode=mode, scenario=scenario, passed=True, directory=str(directory))), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--mode", choices=["direct", "proxy"])
    parser.add_argument("--scenario", choices=["tactics", "convoy"])
    args = parser.parse_args()
    for mode in [args.mode] if args.mode else ["direct", "proxy"]:
        for scenario in [args.scenario] if args.scenario else ["tactics", "convoy"]:
            run(args.image, mode, scenario)
