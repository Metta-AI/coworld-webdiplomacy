"""Serve a claimed Coworld seat's webDiplomacy API on loopback HTTP."""

import argparse
import hmac
import json
import os
import queue
import secrets
import shlex
import signal
import threading
from contextlib import ExitStack
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

MAX_BODY = 128 * 1024


class BridgeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def player_address(value):
    """Resolve a launch response, viewer URL or WS URL without fetching a page."""
    if value.lstrip().startswith("{"):
        launch = json.loads(value)
        if launch.get("kind") != "player":
            raise ValueError("Launch response must contain a ready player seat")
        value = launch["viewer_url"]
    url = urlsplit(value.strip())
    query = parse_qs(url.query, keep_blank_values=True)
    if any(len(values) != 1 for values in query.values()):
        raise ValueError("Repeated URL parameter")
    query = {key: values[0] for key, values in query.items()}
    if url.scheme in {"http", "https"}:
        if not url.path.endswith("/client/player"):
            raise ValueError("Expected a player viewer URL")
        if "address" in query:
            if urlsplit(query["address"]).scheme not in {"ws", "wss"}:
                raise ValueError("Viewer address must be a WebSocket URL")
            return player_address(query["address"])
        url = url._replace(
            scheme="wss" if url.scheme == "https" else "ws", path=url.path.removesuffix("client/player") + "player"
        )
    if (
        url.scheme not in {"ws", "wss"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.fragment
        or not url.path.endswith("/player")
        or not query.get("token")
        or not query.get("slot", "").isdigit()
        or (url.scheme == "ws" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
    ):
        raise ValueError("Expected a secure player URL with slot and token (plain WS is loopback-only)")
    url.port  # Validate the port before handing the credential-bearing URL to the client.
    query["mode"] = "browser"
    return urlunsplit(url._replace(query=urlencode(query)))


class TunnelClient:
    """One outstanding HTTP request; a receiver keeps presence alive while idle."""

    def __init__(self, address, timeout=20):
        self.address = address
        self.timeout = timeout
        self.lock = threading.Lock()
        self.request_lock = threading.Lock()
        self.stopped = threading.Event()
        self.finished = False
        self.unavailable = (503, "Tunnel reconnecting")
        self.pending = None
        self.sequence = 0
        self.ws = None
        self.hello = None
        self.ws, self.hello, self.connection = self._connect()
        self.thread = threading.Thread(target=self._receive, name="webdip-tunnel", daemon=True)
        self.thread.start()

    def _connect(self):
        connection = ExitStack()
        try:
            ws = connection.enter_context(
                connect(self.address, open_timeout=5, close_timeout=1, max_size=16 * 1024 * 1024)
            )
            hello = json.loads(ws.recv(timeout=5))
            if hello.get("type") != "hello" or hello.get("protocol") != "webdip-coworld/1":
                raise BridgeError(502, "Unexpected game protocol")
            if "http-bot-api-v1" not in hello.get("capabilities", []):
                raise BridgeError(502, "Game lacks http-bot-api-v1; use an updated Coworld image")
            if "api_key" in hello["webdip"]:
                raise BridgeError(502, "Seat opened in bot mode; use the player viewer/proxy URL")
            identity = (hello["slot"], hello["webdip"]["game_id"], hello["webdip"]["country_id"])
            if self.hello is not None:
                previous = (self.hello["slot"], self.hello["webdip"]["game_id"], self.hello["webdip"]["country_id"])
                if identity != previous:
                    raise BridgeError(502, "Seat identity changed during reconnect")
            return ws, hello, connection
        except BaseException:
            connection.close()
            raise

    def _fail_pending(self, error):
        # Caller holds self.lock. Queues are unbounded and have at most one item.
        if self.pending is not None:
            self.pending[1].put(error)
            self.pending = None

    def _receive(self):
        while not self.stopped.is_set():
            ws = self.ws
            try:
                for raw in ws:
                    message = json.loads(raw)
                    if message.get("type") == "seat_replaced":
                        with self.lock:
                            self.unavailable = (409, "Seat taken over by another controller; restart bridge")
                            self.ws = None
                            self._fail_pending(BridgeError(*self.unavailable))
                        return
                    if message.get("type") == "game_over":
                        ws.send(json.dumps({"type": "game_over_ack"}))
                        continue
                    if message.get("type") == "game_over_acknowledged":
                        with self.lock:
                            self.finished = True
                            self._fail_pending(BridgeError(410, "Game finished"))
                        return
                    if message.get("type") == "response":
                        with self.lock:
                            if self.pending is not None and message.get("id") == self.pending[0]:
                                self.pending[1].put(message)
                                self.pending = None
            except (WebSocketException, OSError, ValueError, TypeError, AttributeError):
                pass  # Never expose remote error text or credential-bearing URLs.
            finally:
                with self.lock:
                    self.ws = None
                    self._fail_pending(BridgeError(503, "Connection lost; outcome unknown; refetch before retrying"))
                self.connection.close()
            if self.finished:
                return
            for attempt in range(8):
                if self.stopped.wait(min(0.5 * 2**attempt, 5)):
                    return
                try:
                    ws, _, connection = self._connect()
                except (WebSocketException, OSError, TimeoutError):
                    continue
                except BridgeError as error:
                    with self.lock:
                        self.unavailable = (error.status, str(error))
                    return
                except (ValueError, TypeError, KeyError, AttributeError):
                    with self.lock:
                        self.unavailable = (502, "Invalid game handshake; restart with a valid seat URL")
                    return
                with self.lock:
                    if self.stopped.is_set():
                        connection.close()
                        return
                    self.ws = ws
                    self.connection = connection
                break
            else:
                with self.lock:
                    self.unavailable = (503, "Reconnect attempts exhausted; restart bridge")
                return

    def request(self, method, path, body):
        with self.request_lock:
            replies = queue.Queue()
            with self.lock:
                if self.finished:
                    raise BridgeError(410, "Game finished")
                ws = self.ws
                if self.stopped.is_set():
                    raise BridgeError(503, "Bridge stopped")
                if ws is None:
                    raise BridgeError(*self.unavailable)
                self.sequence += 1
                self.pending = (self.sequence, replies)
                request = dict(type="request", id=self.sequence, method=method, path=path, body=body)
            try:
                ws.send(json.dumps(request))
                result = replies.get(timeout=self.timeout)
            except (WebSocketException, OSError):
                raise BridgeError(503, "Connection lost; outcome unknown; refetch before retrying") from None
            except queue.Empty:
                ws.close()  # Drop late responses; reconnect without replaying this request.
                raise BridgeError(504, "Response timed out; outcome unknown; refetch before retrying") from None
            finally:
                with self.lock:
                    self.pending = None
            if isinstance(result, BridgeError):
                raise result
            return result

    def close(self):
        self.stopped.set()
        with self.lock:
            ws = self.ws
            self._fail_pending(BridgeError(503, "Bridge stopped"))
        if ws is not None:
            ws.close()
        # A reconnect may be in its open timeout, hello timeout, or close handshake.
        self.thread.join(timeout=12)


class BridgeServer(HTTPServer):
    def __init__(self, tunnel, port=0):
        self.tunnel = tunnel
        self.api_key = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), BridgeHandler)
        self.timeout = 0.5

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address

    def handle_error(self, request, client_address):
        pass  # HTTP diagnostics must not disclose paths, credentials or private payloads.

    @property
    def environment(self):
        hello = self.tunnel.hello
        return {
            "WEBDIP_URL": f"http://127.0.0.1:{self.server_port}",
            "WEBDIP_API_KEY": self.api_key,
            "WEBDIP_GAME_ID": str(hello["webdip"]["game_id"]),
            "WEBDIP_COUNTRY_ID": str(hello["webdip"]["country_id"]),
            "WEBDIP_SEED": str(hello["rules"]["seed"] * 7 + hello["slot"]),
        }


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        try:
            hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if self.headers.get_all("Host") not in ([host] for host in hosts) or "Origin" in self.headers:
                raise BridgeError(403, "Only local bot clients are allowed")
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment or not self.path.startswith("/") or len(self.path) > 8192:
                raise BridgeError(400, "Invalid request path")
            public = self.command == "GET" and url.path.startswith(("/cache/games/", "/variants/"))
            if not public:
                authorization = self.headers.get("Authorization", "")
                if not hmac.compare_digest(authorization.encode(), ("Bearer " + self.server.api_key).encode()):
                    raise BridgeError(401, "Local Bearer key required")
            if "Transfer-Encoding" in self.headers or len(self.headers.get_all("Content-Length", [])) > 1:
                raise BridgeError(400, "Use one Content-Length; chunked requests are unsupported")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                raise BridgeError(400, "Invalid Content-Length") from None
            if not 0 <= length <= MAX_BODY:
                raise BridgeError(413, "Request body exceeds 128 KiB")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise BridgeError(400, "Incomplete body")
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise BridgeError(400, "Body must be UTF-8") from None
            result = self.server.tunnel.request(self.command, self.path, body)
            headers = result.get("headers", {})
            if (
                type(result.get("status")) is not int
                or not 100 <= result["status"] <= 599
                or not isinstance(result.get("body"), str)
                or not isinstance(headers, dict)
                or any(
                    not isinstance(name, str) or not isinstance(value, str) or "\r" in value or "\n" in value
                    for name, value in headers.items()
                )
            ):
                raise BridgeError(502, "Invalid tunnel response")
            self.reply(result["status"], result["body"], result.get("headers", {}))
        except BridgeError as error:
            self.reply(error.status, str(error))
        except TimeoutError:
            self.reply(408, "Request body timed out")

    def reply(self, status, body, headers=None):
        data = body.encode("utf-8")
        self.send_response(status)
        for name, value in (headers or {"content-type": "text/plain; charset=utf-8"}).items():
            if name.lower() in {"content-type", "x-json"}:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def write_environment(path, environment):
    # Refuse overwrites/symlinks and create with private permissions from the start.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.writelines(f"export {key}={shlex.quote(value)}\n" for key, value in environment.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seat-url-file", type=Path, required=True, help="Private URL or lobby launch JSON file")
    parser.add_argument("--env-file", type=Path, required=True, help="New private shell environment file")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; default chooses a free port")
    args = parser.parse_args()
    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    tunnel = None
    try:
        tunnel = TunnelClient(player_address(args.seat_url_file.read_text()))
        with BridgeServer(tunnel, args.port) as server:
            write_environment(args.env_file, server.environment)
            print(
                f"Bridge listening at {server.environment['WEBDIP_URL']}; environment written to {args.env_file}",
                flush=True,
            )
            while not stopped.is_set():
                server.handle_request()
    except BridgeError as error:
        print(str(error), flush=True)
        return 1
    except (OSError, ValueError, KeyError, TypeError, AttributeError, WebSocketException) as error:
        print(f"Bridge failed ({type(error).__name__}); check the seat URL, port and new env-file path", flush=True)
        return 1
    finally:
        if tunnel is not None:
            tunnel.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
