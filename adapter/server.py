import asyncio
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from aiohttp import ClientSession, web
from api import WebDiplomacy
from protocol import Action, Config


def local_path(uri):
    parsed = urlparse(uri)
    assert parsed.scheme == 'file', 'Local prototype requires file artifact URIs'
    return Path(url2pathname(parsed.path))


class Server:
    def __init__(self):
        self.players = {}
        self.inboxes = [asyncio.Queue() for _ in range(7)]
        self.connected = asyncio.Event()
        self.frames = []
        self.initial_public = {}
        self.finished = False

    async def player(self, request):
        slot = int(request.query['slot'])
        if not 0 <= slot < 7 or not hmac.compare_digest(request.query['token'], request.app['config'].tokens[slot]):
            raise web.HTTPUnauthorized()
        if slot in self.players:
            raise web.HTTPConflict(text='Seat already connected')
        ws = web.WebSocketResponse(autoping=True)
        await ws.prepare(request)
        self.players[slot] = ws
        if len(self.players) == 7:
            self.connected.set()
        async for message in ws:
            if message.type == web.WSMsgType.TEXT:
                await self.inboxes[slot].put(Action.model_validate_json(message.data))
        return ws

    async def global_view(self, request):
        ws = web.WebSocketResponse(autoping=True)
        await ws.prepare(request)
        await ws.send_json(self.frames[-1] if self.frames else self.initial_public)
        async for message in ws:
            if message.type == web.WSMsgType.TEXT and self.frames:
                await ws.send_json(self.frames[-1])
        return ws

    async def replay(self, request):
        ws = web.WebSocketResponse(autoping=True)
        await ws.prepare(request)
        await ws.send_json(self.frames[0])
        frame = 1 % len(self.frames)
        async for message in ws:
            if message.type == web.WSMsgType.TEXT and self.frames:
                await ws.send_json(self.frames[frame])
                frame = (frame + 1) % len(self.frames)
        return ws

    async def episode(self, config):
        await asyncio.wait_for(self.connected.wait(), timeout=config.player_connect_timeout_seconds)
        episode = json.loads(Path('/tmp/episode.json').read_text())
        async with ClientSession() as session:
            api = WebDiplomacy(session, int(episode['gameID']))
            for phase in range(config.max_phases):
                contexts = [await api.context(slot) for slot in range(7)]
                public = await api.public(contexts[0])
                self.frames.append(public)
                active_slots = [slot for slot, context in enumerate(contexts) if context.member.status == 'Playing']
                for slot in active_slots:
                    context = contexts[slot]
                    await self.players[slot].send_json({'type': 'observation', 'context': context.model_dump(), 'public': public})
                pending = {slot: asyncio.create_task(self.inboxes[slot].get()) for slot in active_slots}
                done, remaining = await asyncio.wait(pending.values(), timeout=config.action_timeout_seconds)
                if remaining:
                    slot = next(slot for slot, task in pending.items() if task in remaining)
                    for task in remaining:
                        task.cancel()
                    await asyncio.gather(*remaining, return_exceptions=True)
                    local_path(os.environ['COGAME_PLAYER_FAILURE_URI']).write_text(json.dumps({'failed_policy_index': slot, 'message': 'Player missed the order deadline'}))
                    return
                for slot, task in pending.items():
                    await api.act(slot, contexts[slot], task.result())
                process = await asyncio.create_subprocess_exec('php', '/adapter/engine.php', 'advance', str(api.game_id), stdout=asyncio.subprocess.PIPE)
                stdout, _ = await process.communicate()
                assert process.returncode == 0
                state = json.loads(stdout)
                print(json.dumps({'event': 'adjudicated', 'phase_index': phase, **state}), flush=True)
                if state['phase'] == 'Finished':
                    break
            else:
                process = await asyncio.create_subprocess_exec('php', '/adapter/engine.php', 'draw', str(api.game_id), stdout=asyncio.subprocess.PIPE)
                await process.communicate()
                assert process.returncode == 0
            contexts = [await api.context(slot) for slot in range(7)]
            self.frames.append(await api.public(contexts[0]))
            winners = [c.member.status == 'Won' for c in contexts]
            drawn = [c.member.status == 'Drawn' for c in contexts]
            scores = [float(won) if any(winners) else float(draw) / sum(drawn) for won, draw in zip(winners, drawn)]
            local_path(os.environ['COGAME_SAVE_REPLAY_URI']).write_text(json.dumps(self.frames))
            local_path(os.environ['COGAME_RESULTS_URI']).write_text(json.dumps({'scores': scores, 'phases': len(self.frames) - 1}))
            self.finished = True
            for ws in self.players.values():
                await ws.send_json({'type': 'finished', 'scores': scores})
                await ws.close()


async def player_client(request):
    return web.FileResponse('/adapter/player.html')


async def health(request):
    return web.json_response({'status': 'ready'})


async def viewer(request):
    return web.Response(text='''<!doctype html><meta charset="utf-8"><title>webDiplomacy prototype replay</title>
<h1>webDiplomacy public state</h1><p>Local engineering viewer. Refreshes once per second.</p><pre id="state"></pre>
<script>const replay=location.pathname.endsWith('replay');const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/${replay?'replay':'global'}`);ws.onmessage=e=>document.getElementById('state').textContent=JSON.stringify(JSON.parse(e.data),null,2);ws.onopen=()=>setInterval(()=>ws.send('next'),1000);</script>''', content_type='text/html')


async def main():
    server = Server()
    if 'COGAME_LOAD_REPLAY_URI' in os.environ:
        server.frames = json.loads(local_path(os.environ['COGAME_LOAD_REPLAY_URI']).read_text())
    else:
        config = Config.model_validate_json(local_path(os.environ['COGAME_CONFIG_URI']).read_text())
        episode = json.loads(Path('/tmp/episode.json').read_text())
        async with ClientSession() as session:
            api = WebDiplomacy(session, int(episode['gameID']))
            server.initial_public = await api.public(await api.context(0))
    app = web.Application()
    app.add_routes([web.get('/healthz', health), web.get('/global', server.global_view), web.get('/replay', server.replay), web.get('/client/global', viewer), web.get('/client/replay', viewer)])
    if 'COGAME_LOAD_REPLAY_URI' not in os.environ:
        app['config'] = config
        app.add_routes([web.get('/player', server.player), web.get('/client/player', player_client)])
    runner = web.AppRunner(app, shutdown_timeout=1)
    await runner.setup()
    await web.TCPSite(runner, os.environ.get('COGAME_HOST', '0.0.0.0'), int(os.environ.get('COGAME_PORT', '8080'))).start()
    if 'COGAME_LOAD_REPLAY_URI' not in os.environ:
        await server.episode(config)
        await runner.cleanup()
    else:
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
