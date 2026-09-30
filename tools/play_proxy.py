"""Local GET-only play proxy with the platform's iframe and transport constraints."""

import argparse
import asyncio
import hmac
import html
import json
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

PREFIX = "/episodes/browser-test/proxy"
STATIC_SUFFIXES = (
    ".css",
    ".gif",
    ".glb",
    ".ico",
    ".jpg",
    ".jpeg",
    ".js",
    ".json",
    ".map",
    ".mjs",
    ".otf",
    ".png",
    ".svg",
    ".ttf",
    ".wasm",
    ".webmanifest",
    ".webp",
    ".woff",
    ".woff2",
)
SANDBOX = "allow-scripts allow-same-origin allow-forms allow-pointer-lock"


def create_app(upstream, participant=None):
    app = web.Application()
    app["requests"] = []

    async def proxy(request):
        path = request.match_info["path"]
        app["requests"].append({"method": request.method, "path": path})
        if request.method != "GET":
            raise web.HTTPMethodNotAllowed(request.method, ["GET"])
        allowed = path in {"client/player", "client/global", "player", "global", "ws", "healthz"}
        allowed |= path.startswith(("client/", "assets/")) and path.endswith(STATIC_SUFFIXES)
        if not allowed:
            raise web.HTTPNotFound()
        url = upstream + "/" + path
        async with ClientSession(timeout=ClientTimeout(total=5), trust_env=False) as session:
            if request.headers.get("Upgrade", "").lower() == "websocket":
                # Only query parameters are forwarded. No browser cookies or headers.
                query = dict(request.query)
                if path == "player" and participant:
                    if query.get("slot") != str(participant["slot"]) or not hmac.compare_digest(
                        query.get("token", ""), participant["viewer_token"]
                    ):
                        raise web.HTTPForbidden()
                    query = {
                        "slot": participant["slot"],
                        "token": participant["runtime_token"],
                        "protocol_version": "0.4.0",
                    }
                async with session.ws_connect(url, params=query, timeout=5) as remote:
                    local = web.WebSocketResponse()
                    await local.prepare(request)

                    async def pipe(source, destination):
                        async for message in source:
                            if message.type == WSMsgType.TEXT:
                                await destination.send_str(message.data)
                            elif message.type == WSMsgType.BINARY:
                                await destination.send_bytes(message.data)

                    tasks = [asyncio.create_task(pipe(local, remote)), asyncio.create_task(pipe(remote, local))]
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                    return local
            async with session.get(url, params=request.query, allow_redirects=False) as response:
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                if "text/event-stream" in content_type:
                    raise web.HTTPBadGateway(text="Streaming HTTP is not supported")
                content = await response.read()  # Fully buffered, five-second deadline.
                return web.Response(body=content, status=response.status, headers={"Content-Type": content_type})

    async def frame(request):
        # Visit this on localhost; the iframe uses 127.0.0.1, a separate content origin.
        view = "global" if request.query.get("view") == "global" else "player"
        target = f"http://127.0.0.1:{request.url.port}{PREFIX}/client/{view}?{request.rel_url.raw_query_string}"
        return web.Response(
            content_type="text/html",
            text=f'<!doctype html><title>Lobby constraint harness</title><iframe title="Game" '
            f'width="1000" style="height:min(900px,88vh)" sandbox="{SANDBOX}" referrerpolicy="no-referrer" '
            f'allowfullscreen src="{html.escape(target, quote=True)}"></iframe>',
        )

    async def audit(request):
        return web.json_response(app["requests"])

    app.router.add_get("/frame", frame)
    app.router.add_get("/audit", audit)
    app.router.add_route("*", PREFIX + "/{path:.*}", proxy)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--participant-file", type=Path)
    args = parser.parse_args()
    participant = json.loads(args.participant_file.read_text()) if args.participant_file else None
    web.run_app(create_app(args.upstream, participant), host="127.0.0.1", port=args.port, access_log=None)
