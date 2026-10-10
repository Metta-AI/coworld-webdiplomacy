import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import _path  # noqa: F401  (puts the tools folder on sys.path)
import llm_sidecar_local as sidecar


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Sidecar(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), sidecar.make_handler("sk-test", None, 5))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.real_urlopen = urllib.request.urlopen

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, body):
        request = urllib.request.Request(self.url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with self.real_urlopen(request) as response:
                return response.status, json.loads(response.read()), response.headers
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.loads(error.read()), error.headers

    def test_streaming_is_rejected(self):
        code, body, _ = self.post({"model": "m", "stream": True, "messages": []})
        self.assertEqual(code, 400)
        self.assertEqual(body["error"]["param"], "stream")

    def test_policy_fields_stripped_and_require_parameters_forced(self):
        sent = {}

        def fake_urlopen(request, timeout):
            sent["body"] = json.loads(request.data)
            sent["auth"] = request.headers["Authorization"]
            return FakeResponse(json.dumps({"usage": {"cost": 0.25}, "choices": []}).encode())

        with mock.patch.object(sidecar.urllib.request, "urlopen", fake_urlopen):
            code, body, headers = self.post({"model": "m", "messages": [], "provider": {"order": ["x"]},
                                             "models": ["a"], "user": "u", "temperature": 0.2})
        self.assertEqual(code, 200)
        self.assertEqual(sent["body"], {"model": "m", "messages": [], "temperature": 0.2,
                                        "provider": {"require_parameters": True}})
        self.assertEqual(sent["auth"], "Bearer sk-test")
        self.assertNotIn("sk-test", json.dumps(body) + str(dict(headers)))
        self.assertGreaterEqual(float(headers["X-Coworld-Spend-Usd"]), 0.25)


if __name__ == "__main__":
    unittest.main()
