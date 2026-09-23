import asyncio
import hmac
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, url2pathname, urlopen

from aiohttp import ClientSession, web
from api import WebDiplomacy
from pydantic import ValidationError
from protocol import Action, Config, PlayerFault


def local_path(uri):
    parsed = urlparse(uri)
    if parsed.scheme != 'file':
        raise ValueError(f'Expected a file artifact URI: {uri}')
    return Path(url2pathname(parsed.path))


def read_artifact(uri):
    if urlparse(uri).scheme in ('http', 'https'):
        with urlopen(Request(uri), timeout=30) as response:
            return response.read()
    return local_path(uri).read_bytes()


def write_artifact(uri, data, method_env):
    if urlparse(uri).scheme in ('http', 'https'):
        method = os.environ.get(method_env, 'PUT').upper()
        if method not in ('POST', 'PUT'):
            raise ValueError(f'{method_env} must be PUT or POST')
        request = Request(uri, data=data, method=method, headers={'Content-Type': 'application/json'})
        with urlopen(request, timeout=60):
            return
    target = local_path(uri)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(target)


class Server:
    def __init__(self):
        self.players = {}
        self.claimed_slots = set()
        self.required_slots = set(range(7))
        self.failure = asyncio.get_running_loop().create_future()
        self.expected = {}
        self.actions = {}
        self.actions_ready = asyncio.Event()
        self.connected = asyncio.Event()
        self.frames = []
        self.initial_public = {}
        self.finished = False

    def fail(self, fault):
        if not self.finished and not self.failure.done():
            self.failure.set_result(fault)

    async def receive_action(self, slot, raw):
        # Validation is isolated at the untrusted-message task boundary. Unexpected
        # programming failures still propagate; only schema errors blame the player.
        async def validate():
            return Action.model_validate_json(raw)

        task = asyncio.create_task(validate())
        await asyncio.wait([task])
        error = task.exception()
        if isinstance(error, ValidationError):
            self.fail(PlayerFault(kind='invalid_action', slot=slot))
            return
        if error is not None:
            raise error
        action = task.result()
        if slot not in self.expected:
            self.fail(PlayerFault(kind='invalid_action', slot=slot))
        elif slot in self.actions:
            self.fail(PlayerFault(kind='duplicate_action', slot=slot))
        elif (action.turn, action.phase) != self.expected[slot]:
            self.fail(PlayerFault(kind='stale_action', slot=slot))
        else:
            self.actions[slot] = action
            if len(self.actions) == len(self.expected):
                self.actions_ready.set()

    async def send_player(self, slot, payload, timeout):
        task = asyncio.create_task(self.players[slot].send_json(payload))
        try:
            done, _ = await asyncio.wait([task, self.failure], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            if self.failure in done:
                return
            if task not in done:
                self.fail(PlayerFault(kind='send_timeout', slot=slot))
                return
            error = task.exception()
            if isinstance(error, ConnectionError):
                self.fail(PlayerFault(kind='disconnected', slot=slot))
            elif error is not None:
                raise error
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def wait_for(self, event, timeout):
        task = asyncio.create_task(event.wait())
        try:
            done, _ = await asyncio.wait([task, self.failure], timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            return task in done and not self.failure.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def publish_failure(self):
        fault = self.failure.result()
        write_artifact(
            os.environ['COGAME_PLAYER_FAILURE_URI'],
            json.dumps({'failed_policy_index': fault.slot, 'message': f'Player failure: {fault.kind}'}).encode(),
            'COGAME_PLAYER_FAILURE_METHOD',
        )
        self.finished = True

    async def player(self, request):
        slot_text = request.query.get('slot', '')
        if slot_text not in {str(i) for i in range(7)}:
            raise web.HTTPUnauthorized()
        slot = int(slot_text)
        if not hmac.compare_digest(request.query.get('token', ''), request.app['config'].tokens[slot]):
            raise web.HTTPUnauthorized()
        if slot in self.claimed_slots:
            raise web.HTTPConflict(text='Seat already connected')
        ws = web.WebSocketResponse(autoping=True, max_msg_size=64 * 1024)
        if not ws.can_prepare(request).ok:
            raise web.HTTPBadRequest(text='WebSocket connection required')
        self.claimed_slots.add(slot)
        preparation = asyncio.create_task(ws.prepare(request))
        try:
            done, _ = await asyncio.wait([preparation, self.failure], timeout=request.app['config'].player_connect_timeout_seconds, return_when=asyncio.FIRST_COMPLETED)
            if self.failure in done:
                return ws
            if preparation not in done:
                self.fail(PlayerFault(kind='connect_timeout', slot=slot))
                return ws
            error = preparation.exception()
            if isinstance(error, ConnectionError):
                self.fail(PlayerFault(kind='disconnected', slot=slot))
                return ws
            if error is not None:
                raise error
            self.players[slot] = ws
            if len(self.players) == 7:
                self.connected.set()
            async for message in ws:
                if slot not in self.required_slots:
                    break
                if message.type == web.WSMsgType.TEXT:
                    await self.receive_action(slot, message.data)
                else:
                    self.fail(PlayerFault(kind='invalid_action', slot=slot))
                if self.failure.done():
                    break
        finally:
            preparation.cancel()
            await asyncio.gather(preparation, return_exceptions=True)
            if slot in self.required_slots:
                self.fail(PlayerFault(kind='disconnected', slot=slot))
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
                if message.data == 'all':
                    await ws.send_json({'frames': self.frames})
                else:
                    await ws.send_json(self.frames[frame])
                    frame = (frame + 1) % len(self.frames)
        return ws

    async def episode(self, config):
        if not await self.wait_for(self.connected, config.player_connect_timeout_seconds):
            if not self.failure.done():
                missing = next(slot for slot in range(7) if slot not in self.players)
                self.fail(PlayerFault(kind='connect_timeout', slot=missing))
            self.publish_failure()
            return
        episode = json.loads(Path('/tmp/episode.json').read_text())
        async with ClientSession() as session:
            api = WebDiplomacy(session, int(episode['gameID']))
            for phase in range(config.max_phases):
                contexts = [await api.context(slot) for slot in range(7)]
                public = await api.public(contexts[0])
                self.frames.append(public)
                active_slots = [slot for slot, context in enumerate(contexts) if context.member.status == 'Playing']
                self.required_slots = set(active_slots)
                self.expected = {slot: (contexts[slot].game.turn, contexts[slot].game.phase) for slot in active_slots}
                self.actions = {}
                self.actions_ready.clear()
                if self.failure.done():
                    self.publish_failure()
                    return
                deadline = asyncio.get_running_loop().time() + config.action_timeout_seconds
                for slot in active_slots:
                    context = contexts[slot]
                    await self.send_player(slot, {'type': 'observation', 'context': context.model_dump(), 'public': public}, max(0, deadline - asyncio.get_running_loop().time()))
                    if self.failure.done():
                        self.publish_failure()
                        return
                if not await self.wait_for(self.actions_ready, max(0, deadline - asyncio.get_running_loop().time())):
                    if not self.failure.done():
                        missing = next(slot for slot in active_slots if slot not in self.actions)
                        self.fail(PlayerFault(kind='action_timeout', slot=missing))
                    self.publish_failure()
                    return
                for slot in active_slots:
                    result = await api.act(slot, contexts[slot], self.actions[slot])
                    if isinstance(result, PlayerFault):
                        self.fail(result)
                    if self.failure.done():
                        self.publish_failure()
                        return
                process = await asyncio.create_subprocess_exec('php', '/adapter/engine.php', 'advance', str(api.game_id), stdout=asyncio.subprocess.PIPE)
                stdout, _ = await process.communicate()
                assert process.returncode == 0
                state = json.loads(stdout)
                print(json.dumps({'event': 'adjudicated', 'phase_index': phase, **state}), flush=True)
                if self.failure.done():
                    self.publish_failure()
                    return
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
            if self.failure.done():
                self.publish_failure()
                return
            write_artifact(os.environ['COGAME_SAVE_REPLAY_URI'], json.dumps(self.frames).encode(), 'COGAME_SAVE_REPLAY_METHOD')
            write_artifact(os.environ['COGAME_RESULTS_URI'], json.dumps({'scores': scores, 'phases': len(self.frames) - 1}).encode(), 'COGAME_RESULTS_METHOD')
            self.finished = True
            for slot, ws in self.players.items():
                await self.send_player(slot, {'type': 'finished', 'scores': scores}, 1)
                await ws.close()


async def player_client(request):
    return web.FileResponse('/adapter/player.html')


async def health(request):
    return web.json_response({'status': 'ready'})


async def viewer(request):
    return web.FileResponse('/adapter/viewer.html')


async def map_image(request):
    return web.FileResponse('/application/variants/Classic/resources/smallmap.png')


async def main():
    server = Server()
    if 'COGAME_LOAD_REPLAY_URI' in os.environ:
        server.frames = json.loads(read_artifact(os.environ['COGAME_LOAD_REPLAY_URI']))
    else:
        config = Config.model_validate_json(read_artifact(os.environ['COGAME_CONFIG_URI']))
        episode = json.loads(Path('/tmp/episode.json').read_text())
        async with ClientSession() as session:
            api = WebDiplomacy(session, int(episode['gameID']))
            server.initial_public = await api.public(await api.context(0))
    app = web.Application()
    app.add_routes([web.get('/healthz', health), web.get('/global', server.global_view), web.get('/replay', server.replay), web.get('/map', map_image), web.get('/client/global', viewer), web.get('/client/replay', viewer)])
    if 'COGAME_LOAD_REPLAY_URI' not in os.environ:
        app['config'] = config
        app.add_routes([web.get('/player', server.player), web.get('/client/player', player_client)])
    runner = web.AppRunner(app, shutdown_timeout=1)
    await runner.setup()
    await web.TCPSite(runner, os.environ.get('COGAME_HOST', '0.0.0.0'), int(os.environ.get('COGAME_PORT', '8080'))).start()
    if 'COGAME_LOAD_REPLAY_URI' not in os.environ:
        try:
            await server.episode(config)
        finally:
            server.finished = True
            await asyncio.gather(*(ws.close() for ws in server.players.values()))
            await runner.cleanup()
    else:
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
