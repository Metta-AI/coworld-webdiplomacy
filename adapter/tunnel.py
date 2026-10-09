"""Seat-bound transport for the unmodified upstream browser board."""

import asyncio
import contextlib
import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp

BOT_API_CAPABILITY = "http-bot-api-v1"


class Tunnel:
    def __init__(self, websocket, episode, slot):
        self.websocket = websocket
        self.game_id = episode.game_id
        self.seat = episode.seats[slot]
        self.token = episode.config.tokens[slot]
        self.session = aiohttp.ClientSession(
            headers={"Authorization": "Bearer " + self.token},
            cookie_jar=aiohttp.DummyCookieJar(),
            timeout=aiohttp.ClientTimeout(total=15),
        )
        self.events = None
        self.event_id = None

    async def close(self):
        if self.events:
            self.events.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.events
        await self.session.close()

    def validate(self, message):
        method = message.get("method", "GET")
        path = message.get("path", "")
        body = message.get("body", "")
        if (
            not isinstance(path, str)
            or len(path) > 8192
            or not isinstance(body, str)
            or len(body.encode("utf-8")) > 131072
        ):
            raise ValueError("Invalid request")
        url = urlsplit(path)
        if url.scheme or url.netloc or url.fragment or not path.startswith("/"):
            raise ValueError("Invalid path")
        query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
        if any(len(values) != 1 for values in query.values()):
            raise ValueError("Repeated parameter")
        query = {key: values[0] for key, values in query.items()}
        # PHP normalizes names (e.g. leading spaces and array brackets). Reject
        # aliases so the validated route and seat fields are what PHP receives.
        if any(re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) is None for key in query):
            raise ValueError("Invalid query parameter name")
        content_type = "application/json"
        if url.path == "/api.php":
            route = query.get("route")
            allowed = {
                "game/playercontext": {"GET"},
                "game/sendmessage": {"POST"},
                "game/messagesseen": {"POST"},
                "game/setvote": {"POST"},
                "game/markbackfromleft": {"POST"},
                "game/orders": {"POST"},
                "game/togglevote": {"GET"},
            }
            if method not in allowed.get(route, set()):
                raise ValueError("Not available in this game")
            data = json.loads(body) if body else {}
            if not isinstance(data, dict):
                raise ValueError("Invalid body")
            for fields in (query, data):
                if "gameID" in fields and str(fields["gameID"]) != str(self.game_id):
                    raise ValueError("Wrong game")
                if "countryID" in fields and str(fields["countryID"]) != str(self.seat["country_id"]):
                    raise ValueError("Wrong country")
                if "sbToken" in fields:
                    raise ValueError("Sandbox not available in this game")
            if route == "game/orders":
                orders = data.get("orders")
                if not isinstance(orders, list):
                    raise ValueError("Invalid orders")
                for order in orders:
                    if not isinstance(order, dict) or (
                        "countryID" in order and str(order["countryID"]) != str(self.seat["country_id"])
                    ):
                        raise ValueError("Wrong order country")
        elif url.path == "/ajax.php":
            if method != "POST" or set(query) - {"ready", "notready"}:
                raise ValueError("Only order saves are available")
            form = parse_qs(body, keep_blank_values=True, strict_parsing=True)
            if set(form) != {"context", "contextKey", "orderUpdates"} or any(len(v) != 1 for v in form.values()):
                raise ValueError("Invalid order save")
            context = json.loads(form["context"][0])
            expected = {"gameID": self.game_id, "userID": self.seat["user_id"], "countryID": self.seat["country_id"]}
            if not isinstance(context, dict) or any(str(context.get(k)) != str(v) for k, v in expected.items()):
                raise ValueError("Wrong order seat")
            if context.get("isSandboxMode"):
                raise ValueError("Sandbox not available in this game")
            # Upstream validates contextKey and all orders. Preserve its signed context verbatim.
            content_type = "application/x-www-form-urlencoded"
        else:
            directory = f"/cache/games/{self.game_id // 100}/{self.game_id}/"
            allowed_files = {directory + name + ".json" for name in ("game", "status", "history", "messages")}
            allowed_files.add("/variants/Classic/cache/variant.json")
            if method != "GET" or body or url.path not in allowed_files or set(query) - {"v"}:
                raise ValueError("Not available in this game")
        return method, path, body, content_type

    async def request(self, message):
        response = {"type": "response", "id": message.get("id"), "headers": {}}
        try:
            method, path, body, content_type = self.validate(message)
            async with self.session.request(
                method,
                "http://127.0.0.1:8080" + path,
                data=body or None,
                headers={"Content-Type": content_type},
                allow_redirects=False,
            ) as upstream:
                response.update(status=upstream.status, body=await upstream.text())
                response["headers"] = {
                    name.lower(): value
                    for name, value in upstream.headers.items()
                    if name.lower() in {"content-type", "x-json"}
                }
        except (ValueError, TypeError, KeyError):
            response.update(status=403, body="Not available in this game")
        except (aiohttp.ClientError, TimeoutError):
            response.update(status=502, body="Game server unavailable; please retry")
        await self.websocket.send_json(response)

    async def unsubscribe(self, message):
        if self.events and message.get("id") == self.event_id:
            self.events.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.events
            self.events = None

    async def subscribe(self, message):
        if self.events:
            self.events.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.events
        self.event_id = message.get("id")
        self.events = asyncio.create_task(self.stream_events(message))

    async def stream_events(self, message):
        event_id = message.get("id")
        try:
            path = message.get("path", "")
            if not isinstance(path, str) or len(path) > 8192:
                raise ValueError("Invalid event request")
            # Obtain our own upstream auth, never trust browser-supplied channel names or credentials.
            async with self.session.get(
                "http://127.0.0.1:8080/api.php",
                params={"route": "game/playercontext", "gameID": self.game_id},
            ) as response:
                context = await response.json(content_type=None)
            country = self.seat["country_id"]
            channel = f"private-game{self.game_id}"
            channels = f"{channel},{channel}-files,{channel}-country{country}"
            query = parse_qs(urlsplit(path).query)
            params = {"channelList": channels, "auth": context["sseAuth"]}
            for name in ("have", "since"):
                if name in query:
                    params[name] = query[name][0]
            async with self.session.get(
                "http://127.0.0.1:8080/events?" + urlencode(params),
                timeout=aiohttp.ClientTimeout(total=None, sock_read=40),
            ) as response:
                response.raise_for_status()
                await self.websocket.send_json({"type": "event_open", "id": event_id})
                data = []
                async for raw in response.content:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip(" "))
                    elif not line and data:
                        await self.websocket.send_json({"type": "event", "id": event_id, "data": "\n".join(data)})
                        data = []
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError):
            await self.websocket.send_json({"type": "event_error", "id": event_id})
