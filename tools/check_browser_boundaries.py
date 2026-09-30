"""Live authorization checks for a running browser-test episode."""

import json
from urllib.parse import urlencode

from websockets.sync.client import connect


def check_boundaries(base, tokens, context):
    # Seat 1 may not reuse seat 0's otherwise valid upstream signed-order context.
    address = (
        base.replace("http", "ws")
        + "/player?"
        + urlencode(
            {
                "slot": 1,
                "token": tokens[1],
                "mode": "browser",
            }
        )
    )
    with connect(address, ping_timeout=None) as websocket:
        assert "api_key" not in json.loads(websocket.recv())["webdip"]
        requests = [
            {"path": "/gamemaster.php"},
            {"path": "http://example.com/api.php"},
            {"path": "/cache/games/0/2/game.json"},
            {"path": "/api.php?route=game/playercontext&gameID=2"},
            {"path": "/api.php?route=sandbox/copy"},
            {"path": "/api.php?route=client/error", "method": "POST", "body": "{}"},
            {
                "path": "/ajax.php?ready=on",
                "method": "POST",
                "body": urlencode(
                    {
                        "context": context["orders"]["context"],
                        "contextKey": context["orders"]["contextKey"],
                        "orderUpdates": "[]",
                    }
                ),
            },
        ]
        for request_id, request in enumerate(requests):
            websocket.send(json.dumps({"type": "request", "id": request_id, **request}))
            while True:
                response = json.loads(websocket.recv(timeout=5))
                if response.get("type") == "response":
                    assert response["id"] == request_id and response["status"] == 403, response
                    break
        # Seat-bound context must still work after rejecting malicious requests.
        websocket.send(json.dumps({"type": "request", "id": 100, "path": "/api.php?route=game/playercontext&gameID=1"}))
        response = json.loads(websocket.recv(timeout=5))
        assert response["status"] == 200
        own_country = json.loads(response["body"])["member"]["countryID"]
        assert own_country != context["member"]["countryID"]
        websocket.send(
            json.dumps(
                {
                    "type": "subscribe",
                    "id": 101,
                    "path": "/events?channelList=private-game1-country6&auth=invalid&since=0",
                }
            )
        )
        assert json.loads(websocket.recv(timeout=5))["type"] == "event_open"
        while True:
            event = json.loads(websocket.recv(timeout=5))
            assert event["type"] == "event"
            channel = json.loads(event["data"])["channel"]
            assert channel in {
                "private-game1",
                "private-game1-files",
                f"private-game1-country{own_country}",
                "resync",
                "ping",
                "catchup",
            }
            if channel == "catchup":
                break
        websocket.send(json.dumps({"type": "unsubscribe", "id": 101}))
    return len(requests)
