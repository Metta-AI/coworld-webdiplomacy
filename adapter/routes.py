"""Coworld presence and a seat-authenticated browser transport to upstream."""

import asyncio
import hmac
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from adapter.episode import SOURCE_URL
from adapter.tunnel import BOT_API_CAPABILITY, Tunnel


def install_routes(app, episode):
    @app.get("/client/player")
    def client():
        return HTMLResponse((Path(__file__).parent / "client/player.html").read_text())

    @app.get("/client/global")
    def spectator_client():
        return HTMLResponse((Path(__file__).parent / "viewer.html").read_text())

    @app.websocket("/global")
    async def global_view(websocket: WebSocket):
        await websocket.accept()
        previous = None
        try:
            while True:
                with episode.lock:
                    public = episode.public
                encoded = json.dumps(public)
                if previous != encoded:
                    await websocket.send_text(encoded)
                    previous = encoded
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
                    previous = None
                except TimeoutError:
                    pass
        except WebSocketDisconnect:
            pass

    @app.websocket("/player")
    async def player(websocket: WebSocket):
        query = websocket.query_params
        try:
            slot = int(query.get("slot", "-1"))
        except ValueError:
            slot = -1
        token = query.get("token", "")
        if not 0 <= slot < 7 or not hmac.compare_digest(token.encode(), episode.config.tokens[slot].encode()):
            await websocket.close(code=1008)
            return
        host = websocket.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid_host = (
                parsed.hostname
                and not parsed.username
                and not parsed.password
                and parsed.netloc == host
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and not any(c.isspace() for c in host)
            )
            parsed.port  # Validate an optional numeric port at the untrusted Host boundary.
        except ValueError:
            valid_host = False
        if not valid_host:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        with episode.lock:
            episode.connections[slot] = websocket
        seat = episode.seats[slot]
        webdip = {
            "base_url": "http://" + host,
            "game_id": episode.game_id,
            "country_id": seat["country_id"],
            "country": seat["country"],
        }
        # Lobby proxies replace custom query flags but preserve protocol_version.
        # Launchers explicitly select bot mode; rewritten browser connections omit credentials.
        browser_mode = query.get("mode") == "browser" or ("protocol_version" in query and query.get("mode") != "bot")
        if not browser_mode:
            webdip["api_key"] = token
        tunnel = Tunnel(websocket, episode, slot) if browser_mode else None
        sent_started = False
        sent_finished = False
        try:
            await websocket.send_json(
                {
                    "type": "hello",
                    "protocol": "webdip-coworld/1",
                    "capabilities": [BOT_API_CAPABILITY],
                    "slot": slot,
                    "webdip": webdip,
                    "rules": episode.config.model_dump(exclude={"tokens"}),
                    "source_url": SOURCE_URL,
                }
            )
            while True:
                with episode.lock:
                    started, finished, result = episode.started, episode.finished, episode.result
                    current = episode.connections.get(slot) is websocket
                if not current:
                    # Carry takeover as application data: platform proxies may not
                    # preserve WebSocket close codes across the relay.
                    await websocket.send_json({"type": "seat_replaced"})
                    await websocket.close(code=1000)
                    return
                if started and not sent_started:
                    await websocket.send_json({"type": "game_started"})
                    sent_started = True
                if finished and not sent_finished:
                    await websocket.send_json({"type": "game_over", "results": result})
                    sent_finished = True
                try:
                    message = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                    if not isinstance(message, dict):
                        raise ValueError("Expected an object")
                    if tunnel and message.get("type") == "request":
                        await tunnel.request(message)
                    elif tunnel and message.get("type") == "subscribe":
                        await tunnel.subscribe(message)
                    elif tunnel and message.get("type") == "unsubscribe":
                        await tunnel.unsubscribe(message)
                    if message.get("type") == "game_over_ack" and sent_finished:
                        with episode.lock:
                            episode.acknowledged.add(slot)
                        await websocket.send_json({"type": "game_over_acknowledged"})
                except TimeoutError:
                    pass
                except (ValueError, TypeError):
                    await websocket.close(code=1003)
                    return
        except WebSocketDisconnect:
            pass
        finally:
            if tunnel:
                await tunnel.close()
            with episode.lock:
                if episode.connections.get(slot) is websocket:
                    del episode.connections[slot]
