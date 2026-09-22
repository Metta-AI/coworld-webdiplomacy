"""Readable starter: hold, disband retreats, waive builds, vote draw after four turns."""
import asyncio
import os

from aiohttp import ClientSession, WSMsgType


async def main():
    async with ClientSession() as session:
        async with session.ws_connect(os.environ['COWORLD_PLAYER_WS_URL'], heartbeat=None) as ws:
            async for event in ws:
                if event.type != WSMsgType.TEXT:
                    continue
                observation = event.json()
                if observation['type'] == 'finished':
                    return
                context = observation['context']
                phase = context['game']['phase']
                action = {'turn': context['game']['turn'], 'phase': phase, 'draw': context['game']['turn'] >= 3, 'orders': []}
                for order in context['orders']['orders']:
                    order_type = {'Diplomacy': 'Hold', 'Retreats': 'Disband', 'Builds': 'Wait'}[phase]
                    action['orders'].append({'type': order_type, 'terrID': 0 if phase == 'Builds' else order['terrID']})
                await ws.send_json(action)


asyncio.run(main())
