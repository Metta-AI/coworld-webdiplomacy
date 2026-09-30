"""Replay-only server retained until the static viewer migration."""

import asyncio
import json
import os
import signal
from pathlib import Path

from aiohttp import web
from artifacts import read_artifact


async def main():
    frames = json.loads(read_artifact(os.environ["COGAME_LOAD_REPLAY_URI"]))

    async def health(request):
        return web.json_response({"status": "ready"})

    async def viewer(request):
        return web.FileResponse(Path(__file__).with_name("viewer.html"))

    async def map_image(request):
        return web.FileResponse("/application/variants/Classic/resources/smallmap.png")

    async def replay(request):
        ws = web.WebSocketResponse(autoping=True)
        await ws.prepare(request)
        await ws.send_json(frames[0])
        index = 1 % len(frames)
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                if message.data == "all":
                    await ws.send_json({"frames": frames})
                else:
                    await ws.send_json(frames[index])
                    index = (index + 1) % len(frames)
        return ws

    app = web.Application()
    app.add_routes(
        [
            web.get("/healthz", health),
            web.get("/replay", replay),
            web.get("/global", replay),
            web.get("/client/replay", viewer),
            web.get("/client/global", viewer),
            web.get("/map", map_image),
        ]
    )
    runner = web.AppRunner(app, shutdown_timeout=1)
    await runner.setup()
    await web.TCPSite(
        runner, os.environ.get("COGAME_HOST", "0.0.0.0"), int(os.environ.get("COGAME_PORT", "8080"))
    ).start()
    stopping = asyncio.Event()
    for number in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(number, stopping.set)
    await stopping.wait()
    await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
