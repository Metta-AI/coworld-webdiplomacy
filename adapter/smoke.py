import asyncio
import json
import subprocess
from pathlib import Path

import aiohttp
from api import WebDiplomacy
from protocol import Action, Order


async def main():
    episode = json.loads(Path('/tmp/episode.json').read_text())
    assert episode['phase'] == 'Diplomacy', episode
    async with aiohttp.ClientSession() as session:
        api = WebDiplomacy(session, int(episode['gameID']))
        contexts = [await api.context(slot) for slot in range(7)]
        assert [c.member.countryID for c in contexts] == list(range(1, 8))
        await api.request(0, 'game/sendmessage', body={'gameID': api.game_id, 'countryID': 1, 'toCountryID': 2, 'message': 'private-sentinel-coworld'})
        assert 'private-sentinel-coworld' in (await api.context(1)).model_dump_json()
        assert 'private-sentinel-coworld' not in (await api.context(2)).model_dump_json()
        assert 'private-sentinel-coworld' not in json.dumps(await api.public(await api.context(0)))
        for step in range(4):
            contexts = [await api.context(slot) for slot in range(7)]
            for slot, context in enumerate(contexts):
                action = Action(turn=context.game.turn, phase=context.game.phase, draw=step == 3,
                    orders=[Order(type='Hold', terrID=int(order['terrID'])) for order in context.orders.orders])
                await api.act(slot, context, action)
            completed = subprocess.run(['php', '/adapter/engine.php', 'advance', str(api.game_id)], capture_output=True, text=True, check=True)
            print('Adjudicated', completed.stdout, flush=True)
        final = await api.context(0)
        assert final.game.gameOver == 'Drawn', final
        public = await api.public(final)
        assert 'private-sentinel-coworld' not in json.dumps(public)
        Path('/tmp/replay.json').write_text(json.dumps(public))
        print('PASS: seven API players, four adjudications, unanimous draw, private message separation, public replay', flush=True)

asyncio.run(main())
