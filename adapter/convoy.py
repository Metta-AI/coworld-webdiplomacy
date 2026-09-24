"""Exercise a two-phase Classic convoy against the pinned adjudicator."""

import asyncio
import json
import subprocess
from pathlib import Path

import aiohttp
from api import WebDiplomacy
from protocol import Action, Order


async def main():
    episode = json.loads(Path('/tmp/episode.json').read_text())
    async with aiohttp.ClientSession() as session:
        api = WebDiplomacy(session, int(episode['gameID']))
        public = await api.public(await api.context(0))
        territories = {territory['name']: territory['id'] for territory in public['variant']['territories']}
        for step in range(2):
            contexts = [await api.context(slot) for slot in range(7)]
            assert contexts[0].game.phase == 'Diplomacy'
            for slot, context in enumerate(contexts):
                orders = []
                for original in context.orders.orders:
                    origin = int(original['terrID'])
                    order = Order(type='Hold', terrID=origin)
                    if step == 0 and slot == 1:
                        if origin == territories['Brest']:
                            order = Order(type='Move', terrID=origin, toTerrID=territories['English Channel'])
                        elif origin == territories['Paris']:
                            order = Order(type='Move', terrID=origin, toTerrID=territories['Brest'])
                    elif step == 0 and slot == 0 and origin == territories['London']:
                        order = Order(type='Move', terrID=origin, toTerrID=territories['North Sea'])
                    elif step == 1 and slot == 1:
                        if origin == territories['Brest']:
                            order = Order(
                                type='Move', terrID=origin, toTerrID=territories['London'],
                                viaConvoy='Yes', convoyPath=[territories['Brest'], territories['English Channel']],
                            )
                        elif origin == territories['English Channel']:
                            order = Order(
                                type='Convoy', terrID=origin,
                                fromTerrID=territories['Brest'], toTerrID=territories['London'],
                                convoyPath=[territories['Brest'], territories['English Channel']],
                            )
                    orders.append(order)
                action = Action(turn=context.game.turn, phase=context.game.phase, orders=orders)
                assert (await api.act(slot, context, action)).kind == 'accepted'
            process = subprocess.run(
                ['php', '/adapter/engine.php', 'advance', str(api.game_id)],
                capture_output=True, text=True, check=True,
            )
            state = json.loads(process.stdout)
            print('Convoy phase', step, state, flush=True)
        final = await api.public(await api.context(0))
        units = final['history']['phases'][-1]['units']
        assert any(unit['countryID'] == 2 and unit['terrID'] == territories['London'] for unit in units)
        print('PASS: French army convoys from Brest through English Channel to London', flush=True)


asyncio.run(main())
