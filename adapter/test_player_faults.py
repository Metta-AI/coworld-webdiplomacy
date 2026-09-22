import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from aiohttp import web, WSServerHandshakeError, ClientResponseError
from aiohttp.test_utils import TestClient, TestServer
from api import WebDiplomacy
from protocol import Action, Config, Context, PlayerFault
from server import Server


class PlayerFaultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = Server()
        self.config = Config(tokens=[f'token-{slot}' for slot in range(7)], player_connect_timeout_seconds=0.02)
        app = web.Application()
        app['config'] = self.config
        app.router.add_get('/player', self.server.player)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.temp = tempfile.TemporaryDirectory()
        self.failure_path = Path(self.temp.name) / 'failure.json'
        self.env = patch.dict(os.environ, COGAME_PLAYER_FAILURE_URI=self.failure_path.as_uri(), COGAME_RESULTS_URI=(self.failure_path.parent / 'results.json').as_uri(), COGAME_SAVE_REPLAY_URI=(self.failure_path.parent / 'replay.json').as_uri())
        self.env.start()

    async def asyncTearDown(self):
        self.server.finished = True
        await asyncio.gather(*(ws.close() for ws in self.server.players.values()))
        await self.client.close()
        self.env.stop()
        self.temp.cleanup()

    async def connect(self, slot=0):
        return await self.client.ws_connect(f'/player?slot={slot}&token=token-{slot}')

    async def expect_fault(self, kind, slot=0):
        fault = await asyncio.wait_for(asyncio.shield(self.server.failure), 1)
        self.assertEqual(fault, PlayerFault(kind=kind, slot=slot))
        self.server.publish_failure()
        self.assertEqual(json.loads(self.failure_path.read_text()), {'failed_policy_index': slot, 'message': f'Player failure: {kind}'})
        self.assertFalse(self.failure_path.with_name('failure.json.tmp').exists())
        self.assertFalse((self.failure_path.parent / 'results.json').exists())
        self.assertFalse((self.failure_path.parent / 'replay.json').exists())

    async def test_invalid_json_is_attributed_without_echoing_payload(self):
        ws = await self.connect(3)
        await ws.send_str('secret invalid json')
        await self.expect_fault('invalid_action', 3)
        self.assertNotIn('secret', self.failure_path.read_text())

    async def test_invalid_schema_and_coercion_are_rejected(self):
        self.server.expected = {0: (0, 'Diplomacy')}
        ws = await self.connect()
        await ws.send_json({'turn': '0', 'phase': 'Diplomacy', 'orders': []})
        await self.expect_fault('invalid_action')

    async def test_stale_action(self):
        self.server.expected = {0: (2, 'Diplomacy')}
        ws = await self.connect()
        await ws.send_json({'turn': 1, 'phase': 'Diplomacy', 'orders': []})
        await self.expect_fault('stale_action')

    async def test_duplicate_is_not_buffered_for_next_phase(self):
        self.server.expected = {0: (0, 'Diplomacy')}
        ws = await self.connect()
        action = {'turn': 0, 'phase': 'Diplomacy', 'orders': []}
        await ws.send_json(action)
        await asyncio.wait_for(self.server.actions_ready.wait(), 1)
        await ws.send_json(action)
        await self.expect_fault('duplicate_action')
        self.assertEqual(len(self.server.actions), 1)

    async def test_early_action_is_rejected(self):
        ws = await self.connect()
        await ws.send_json({'turn': 0, 'phase': 'Diplomacy', 'orders': []})
        await self.expect_fault('invalid_action')

    async def test_disconnect_is_immediate(self):
        ws = await self.connect(4)
        await ws.close()
        await self.expect_fault('disconnected', 4)

    async def test_connection_deadline_attributes_missing_seat(self):
        await self.connect(0)
        await self.server.episode(self.config)
        await self.expect_fault('connect_timeout', 1)

    async def test_wait_timeout_leaves_no_pending_event_task(self):
        before = asyncio.all_tasks()
        self.assertFalse(await self.server.wait_for(asyncio.Event(), 0.01))
        self.assertEqual(asyncio.all_tasks(), before)
        self.assertFalse(self.server.failure.done())

    async def test_wait_interrupts_on_player_fault(self):
        wait = asyncio.create_task(self.server.wait_for(asyncio.Event(), 60))
        self.server.fail(PlayerFault(kind='action_timeout', slot=2))
        self.assertFalse(await asyncio.wait_for(wait, 1))
        await self.expect_fault('action_timeout', 2)

    async def test_binary_and_oversized_messages_fail(self):
        ws = await self.connect()
        await ws.send_bytes(b'not json')
        await self.expect_fault('invalid_action')

    async def test_oversized_message_is_bounded(self):
        ws = await self.connect()
        await ws.send_str('x' * (64 * 1024 + 1))
        await self.expect_fault('invalid_action')

    async def test_bad_auth_does_not_fault_any_seat(self):
        response = await self.client.get('/player?slot=bogus&token=wrong')
        self.assertEqual(response.status, 401)
        self.assertFalse(self.server.failure.done())

    async def test_api_stale_phase_returns_typed_fault_before_network(self):
        context = Context.model_validate({'game': {'gameID': 1, 'turn': 2, 'phase': 'Diplomacy', 'gameOver': 'No'}, 'member': {'countryID': 1, 'status': 'Playing', 'votes': []}, 'files': {}, 'orders': {'orders': []}, 'messages': {}})
        api = WebDiplomacy(self.client.session, 1)
        result = await api.act(5, context, Action(turn=1, phase='Diplomacy', orders=[]))
        self.assertEqual(result, PlayerFault(kind='stale_action', slot=5))

    async def test_action_deadline_publishes_failure_without_results(self):
        self.server.players = {slot: SimpleNamespace(send_json=AsyncMock(), close=AsyncMock()) for slot in range(7)}
        self.server.connected.set()
        context = Context.model_validate({'game': {'gameID': 1, 'turn': 0, 'phase': 'Diplomacy', 'gameOver': 'No'}, 'member': {'countryID': 1, 'status': 'Playing', 'votes': []}, 'files': {}, 'orders': {'orders': []}, 'messages': {}})
        self.config.action_timeout_seconds = 0.01
        with patch('server.Path.read_text', return_value='{"gameID":1}'), patch('server.WebDiplomacy') as api:
            api.return_value.context = AsyncMock(return_value=context)
            api.return_value.public = AsyncMock(return_value={})
            await self.server.episode(self.config)
        await self.expect_fault('action_timeout', 0)

    async def test_socket_write_disconnect_is_attributed(self):
        self.server.players[2] = SimpleNamespace(send_json=AsyncMock(side_effect=ConnectionResetError()), close=AsyncMock())
        await self.server.send_player(2, {'type': 'observation'}, 1)
        await self.expect_fault('disconnected', 2)

    async def test_upstream_validation_response_is_typed(self):
        response = SimpleNamespace(status=400)
        manager = AsyncMock()
        manager.__aenter__.return_value = response
        session = SimpleNamespace(request=lambda *args, **kwargs: manager)
        result = await WebDiplomacy(session, 1).request(4, 'game/orders', player_action=True, body={})
        self.assertEqual(result, PlayerFault(kind='rejected_action', slot=4))

    async def test_blocked_send_is_interrupted_by_other_seat_fault(self):
        self.server.players[0] = SimpleNamespace(send_json=lambda payload: asyncio.Event().wait(), close=AsyncMock())
        before = asyncio.all_tasks()
        send = asyncio.create_task(self.server.send_player(0, {}, 60))
        await asyncio.sleep(0)
        self.server.fail(PlayerFault(kind='disconnected', slot=4))
        await asyncio.wait_for(send, 1)
        await self.expect_fault('disconnected', 4)
        self.assertEqual(asyncio.all_tasks(), before)

    async def test_blocked_send_has_deadline(self):
        self.server.players[0] = SimpleNamespace(send_json=lambda payload: asyncio.Event().wait(), close=AsyncMock())
        await self.server.send_player(0, {}, 0.01)
        await self.expect_fault('send_timeout', 0)

    async def test_eliminated_seat_disconnect_does_not_abort_game(self):
        ws = await self.connect(2)
        self.server.required_slots.remove(2)
        await ws.close()
        await asyncio.sleep(0)
        self.assertFalse(self.server.failure.done())

    async def test_concurrent_duplicate_connections_reserve_one_seat(self):
        results = await asyncio.gather(self.connect(1), self.connect(1), return_exceptions=True)
        rejected = [result for result in results if isinstance(result, WSServerHandshakeError)]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].status, 409)
        self.assertEqual(set(self.server.players), {1})
        self.assertFalse(self.server.failure.done())

    async def test_infrastructure_http_errors_are_not_player_faults(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                error = ClientResponseError(SimpleNamespace(real_url='private-api'), (), status=status)
                response = SimpleNamespace(status=status, raise_for_status=Mock(side_effect=error))
                manager = AsyncMock()
                manager.__aenter__.return_value = response
                session = SimpleNamespace(request=lambda *args, **kwargs: manager)
                with self.assertRaises(ClientResponseError):
                    await WebDiplomacy(session, 1).request(0, 'game/orders', player_action=True, body={})

    async def test_eliminated_seat_cannot_fault_remaining_players(self):
        ws = await self.connect(2)
        self.server.required_slots.remove(2)
        await ws.send_str('ignored after elimination')
        await ws.receive()
        self.assertFalse(self.server.failure.done())

    async def test_failed_socket_upgrade_is_attributed_immediately(self):
        request = SimpleNamespace(query={'slot': '0', 'token': 'token-0'}, app={'config': self.config})
        socket = SimpleNamespace(can_prepare=lambda request: SimpleNamespace(ok=True), prepare=AsyncMock(side_effect=ConnectionResetError()))
        with patch('server.web.WebSocketResponse', return_value=socket):
            await self.server.player(request)
        await self.expect_fault('disconnected', 0)
        self.assertFalse(self.server.players)

    async def test_blocked_socket_upgrade_has_deadline(self):
        request = SimpleNamespace(query={'slot': '0', 'token': 'token-0'}, app={'config': self.config})
        socket = SimpleNamespace(can_prepare=lambda request: SimpleNamespace(ok=True), prepare=lambda request: asyncio.Event().wait())
        before = asyncio.all_tasks()
        with patch('server.web.WebSocketResponse', return_value=socket):
            await self.server.player(request)
        await self.expect_fault('connect_timeout', 0)
        self.assertEqual(asyncio.all_tasks(), before)
