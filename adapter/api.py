from aiohttp import ClientSession
from pydantic import TypeAdapter
from protocol import Action, ActionAccepted, AppliedOrder, Context, PlayerFault


class WebDiplomacy:
    def __init__(self, session: ClientSession, game_id: int):
        self.session = session
        self.game_id = game_id

    async def request(self, slot, route, *, body=None, json_response=True, player_action=False, **params):
        async with self.session.request(
            'GET' if body is None else 'POST',
            'http://127.0.0.1:8090/api.php',
            params={'route': route, **params},
            json=body,
            headers={'Authorization': f'Bearer bot{slot + 1}'},
        ) as response:
            if player_action and response.status == 400:
                return PlayerFault(kind='rejected_action', slot=slot)
            response.raise_for_status()
            return await response.json(content_type=None) if json_response else await response.text()

    async def context(self, slot):
        return Context.model_validate(await self.request(slot, 'game/playercontext', gameID=self.game_id, orders=1, messages=1))

    async def public(self, context):
        result = {}
        for name, file in context.files.items():
            async with self.session.get(f'http://127.0.0.1:8090/{file.url}', params={'v': file.version}) as response:
                response.raise_for_status()
                result[name] = await response.json(content_type=None)
        return result

    async def act(self, slot: int, context: Context, action: Action) -> ActionAccepted | PlayerFault:
        if (action.turn, action.phase) != (context.game.turn, context.game.phase):
            return PlayerFault(kind='stale_action', slot=slot)
        country = context.member.countryID
        # All transport failures remain game errors. Only player-request validation responses
        # become attributed rejections; response bodies may contain private data.
        for message in action.messages:
            result = await self.request(slot, 'game/sendmessage', player_action=True, body={'gameID': self.game_id, 'countryID': country, **message.model_dump()})
            if isinstance(result, PlayerFault):
                return result
        if action.draw != ('Draw' in context.member.votes):
            result = await self.request(slot, 'game/togglevote', gameID=self.game_id, countryID=country, vote='Draw', json_response=False, player_action=True)
            if isinstance(result, PlayerFault):
                return result
        result = await self.request(slot, 'game/orders', player_action=True, body={
            'gameID': self.game_id, 'countryID': country, 'turn': action.turn, 'phase': action.phase,
            'ready': 'Yes', 'orders': [order.model_dump(exclude_none=True) for order in action.orders],
        })
        if isinstance(result, PlayerFault):
            return result
        applied = TypeAdapter(list[AppliedOrder]).validate_python(result)
        by_territory = {order.terrID: order for order in applied}
        for order in action.orders:
            if order.type == 'Wait':
                if not any(item.type == 'Wait' for item in applied):
                    return PlayerFault(kind='rejected_action', slot=slot)
                continue
            if order.type in ('Build Army', 'Build Fleet', 'Destroy'):
                if not any(item.type == order.type and item.toTerrID == order.toTerrID for item in applied):
                    return PlayerFault(kind='rejected_action', slot=slot)
                continue
            if order.terrID not in by_territory:
                return PlayerFault(kind='rejected_action', slot=slot)
            observed = by_territory[order.terrID]
            if observed.type != order.type:
                return PlayerFault(kind='rejected_action', slot=slot)
            if (
                order.type in ('Move', 'Support hold', 'Support move', 'Convoy', 'Retreat')
                and observed.toTerrID != order.toTerrID
            ):
                return PlayerFault(kind='rejected_action', slot=slot)
            if order.type in ('Support move', 'Convoy') and observed.fromTerrID != order.fromTerrID:
                return PlayerFault(kind='rejected_action', slot=slot)
            if order.type == 'Move' and observed.viaConvoy != order.viaConvoy:
                return PlayerFault(kind='rejected_action', slot=slot)
        return ActionAccepted()
