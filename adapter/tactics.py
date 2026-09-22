"""Real-engine opening producing builds, a supported attack, and a retreat."""
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
        territories = {t['name']: t['id'] for t in public['variant']['territories']}
        steps = [
            {'Paris': ('Move', 'Burgundy'), 'Munich': ('Move', 'Ruhr'), 'Berlin': ('Move', 'Kiel'), 'Kiel': ('Move', 'Baltic Sea')},
            {'Burgundy': ('Move', 'Belgium'), 'Ruhr': ('Move', 'Holland'), 'Kiel': ('Move', 'Ruhr')},
            {},
            {'Holland': ('Move', 'Belgium'), 'Ruhr': ('Support move', 'Belgium', 'Holland')},
            {'Belgium': ('Retreat', 'Picardy')},
        ]
        phases = []
        for step, overrides in enumerate(steps):
            contexts = [await api.context(slot) for slot in range(7)]
            phase = contexts[0].game.phase
            phases.append(phase)
            for slot, context in enumerate(contexts):
                orders = []
                for original in context.orders.orders:
                    terr_id = original['terrID']
                    if phase == 'Builds':
                        home = 'Paris' if slot == 1 else 'Munich'
                        orders.append(Order(type='Build Army', terrID=territories[home], toTerrID=territories[home]))
                    else:
                        order = Order(type='Hold' if phase == 'Diplomacy' else 'Disband', terrID=terr_id)
                        for name, override in overrides.items():
                            if territories[name] == terr_id:
                                order.type = override[0]
                                order.toTerrID = territories[override[1]]
                                if len(override) == 3:
                                    order.fromTerrID = territories[override[2]]
                        orders.append(order)
                assert (await api.act(slot, context, Action(turn=context.game.turn, phase=phase, orders=orders))).kind == 'accepted'
            result = subprocess.run(['php', '/adapter/engine.php', 'advance', str(api.game_id)], capture_output=True, text=True, check=True)
            state = json.loads(result.stdout)
            assert (state['phase'], int(state['turn'])) != (phase, contexts[0].game.turn), result.stdout
            print('Tactical phase', step, result.stdout, flush=True)
        assert phases == ['Diplomacy', 'Diplomacy', 'Builds', 'Diplomacy', 'Retreats'], phases
        final = await api.public(await api.context(0))
        units = final['history']['phases'][-1]['units']
        assert any(u['countryID'] == 2 and u['terrID'] == territories['Picardy'] for u in units)
        assert any(u['countryID'] == 4 and u['terrID'] == territories['Belgium'] for u in units)
        Path('/tmp/tactical-replay.json').write_text(json.dumps(final))
        print('PASS: legal moves, two army builds, supported dislodgement, legal retreat', flush=True)


asyncio.run(main())
