"""Same API scenario against the Coworld and the pinned upstream core compose stack."""

import argparse
import json
import re
import threading
import traceback
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from players.scenarios import play, public, wait_phase
from tools.check_episode import wait_for
from tools.player_fixture import game
from tools.stock_stack import StockStack


class Events:
    def __init__(self, api):
        context = api.context()
        channel = f"private-game{api.game_id}"
        query = urlencode(
            dict(channelList=f"{channel},{channel}-files,{channel}-country{api.country_id}", auth=context["sseAuth"])
        )
        self.response = urlopen(api.url + "/events?" + query, timeout=3)
        self.messages = []
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        try:
            for line in self.response:
                if line.startswith(b"data: "):
                    self.messages.append(json.loads(line[6:]))
        except (OSError, ValueError):
            pass

    def result(self):
        events = set()
        for message in self.messages:
            if message["channel"] == "ping":
                continue
            channel = re.sub(r"private-game\d+", "private-game<ID>", message["channel"])
            body = json.loads(message["message"])
            event = body["event"]
            if event == "files":
                events.update((channel, "files", key) for key in body["data"])
            else:
                events.add((channel, event, json.dumps(body["data"], sort_keys=True)))
        assert ("private-game<ID>", "overview", '"processed"') in events, events
        return sorted(events)


class Normalize:
    """Canonicalize generated identities, timestamps and signatures derived from them."""

    times = {
        "generated",
        "processTime",
        "startTime",
        "finishTime",
        "timeSent",
        "cursor",
        "lastMessageTime",
        "tokenExpireTime",
        "lastOnline",
        "timeLoggedIn",
    }
    ids = {"gameID", "realGameID", "userID", "memberID", "unitID", "orderID", "maxOrderID", "retreatingUnitID"}

    def __init__(self):
        self.maps = {}

    def identity(self, kind, value):
        if not value:
            return value
        table = self.maps.setdefault(kind, {})
        canonical = table.setdefault(str(value), len(table) + 1)
        return str(canonical) if isinstance(value, str) else canonical

    def __call__(self, value, key=""):
        if isinstance(value, dict):
            result = {}
            for k, item in value.items():
                id_kind = k
                if k == "id":
                    if "retreating" in value:
                        id_kind = "unitID"
                    elif "unitType" in value:
                        id_kind = "orderID"
                    elif "message" in value or "vote" in value:
                        id_kind = "messageID"
                    elif "username" in value:
                        id_kind = "userID"
                if id_kind in self.ids or id_kind == "messageID":
                    result[k] = self.identity(id_kind, item)
                elif k in self.times or (k == "lastSeen" and isinstance(item, int)):
                    result[k] = "timestamp" if item else item
                elif k in ("sseAuth", "contextKey", "version"):
                    result[k] = "<generated>"
                elif k == "context" and isinstance(item, str):
                    result[k] = self(json.loads(item))
                else:
                    result[k] = self(item, k)
            return result
        if isinstance(value, list):
            return [self(item, key) for item in value]
        if isinstance(value, str) and key == "url":
            return re.sub(r"cache/games/\d+/\d+/", "cache/games/ID/", value)
        return value


def scenario(mode, clients):
    wait_phase(clients[1])
    events = Events(clients[2])
    trace = {"snapshots": [], "saved": [], "votes": []}
    for country, api in clients.items():
        original_orders = api.orders
        original_vote = api.vote

        def orders(context, requested, *, ready="Yes", call=original_orders, country=country):
            saved = call(context, requested, ready=ready)
            if ready == "No":
                trace["saved"].append({"country": country, "orders": saved})
            return saved

        def vote(kind, enabled=True, call=original_vote, country=country):
            response = call(kind, enabled)
            trace["votes"].append({"country": country, "response": response})
            return response

        api.orders, api.vote = orders, vote

    def observe(clients, contexts):
        target = contexts[1]["game"]

        def committed():
            data = public(clients[1].context(), clients[1].url)
            return data if (data["game"]["turn"], data["game"]["phase"]) == (target["turn"], target["phase"]) else None

        files = wait_for(committed)
        trace["snapshots"].append({"contexts": contexts, "files": files})

    play(mode, clients, observe)
    wait_for(lambda: events.messages)
    trace["events"] = events.result()
    if mode == "smoke":
        assert ("private-game<ID>-country2", "message", '"messageSent"') in trace["events"], trace["events"]
    return trace


def run(image, directory):
    directory.mkdir(parents=True, exist_ok=True)
    stock = StockStack(directory)
    try:
        stock.start()
        stock.prepare()
        for mode in ("smoke", "tactics", "convoy"):
            with game(image, "p4-compat-" + mode) as (clients, artifacts, container, sockets):
                config = json.loads((artifacts / "config.json").read_text())
                config["countries"] = [
                    next(country for country, api in clients.items() if api.key == token) for token in config["tokens"]
                ]
                # Capture in country order in both environments.
                ours = scenario(mode, dict(sorted(clients.items())))
            upstream = scenario(mode, dict(sorted(stock.create(config).items())))
            for name, trace in [("coworld", ours), ("stock", upstream)]:
                (directory / f"{mode}-{name}.json").write_text(json.dumps(trace, indent=2))
                (directory / f"{mode}-{name}-normalized.json").write_text(json.dumps(Normalize()(trace), indent=2))
            assert Normalize()(ours) == Normalize()(upstream), f"{mode}: comparison differs; see {directory}"
            print(
                f"{mode}: identical normalized contexts, files, orders, votes, messages, phase outcomes and SSE events",
                flush=True,
            )
    except Exception:
        (directory / "failure.txt").write_text(traceback.format_exc())
        raise
    finally:
        logs = stock.compose("logs", "--no-color", capture_output=True, text=True)
        (directory / "stock-services.log").write_text(logs.stdout + logs.stderr)
        stock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--directory", type=Path, default=Path("tmp/p4-compatibility"))
    args = parser.parse_args()
    run(args.image, args.directory)
