#!/usr/bin/env python3
"""Local stand-in for the hosted Coworld LLM sidecar, so local episodes use the hosted LLM path.

Hosted player pods reach a model only through their sidecar at COWORLD_LLM_ENDPOINT.
`coworld run-episode --use-llm` has no sidecar: it forwards the host's
COWORLD_LLM_ENDPOINT into the containers. Run this on the host and point that variable
at it. Standard-library Python 3.12+.

Usage:
    export OPENROUTER_API_KEY=...        # never logged or written anywhere by this script
    python3 games/webdiplomacy/tools/llm_sidecar_local.py --port 9177 --ledger RUN_DIR/llm_ledger.jsonl
    COWORLD_LLM_ENDPOINT=http://host.docker.internal:9177 \\
        python3 games/webdiplomacy/tools/wd.py local --image IMG --use-llm --variant classic-press-short --out DIR

Run it outside any command sandbox: a sandboxed process never receives the
containers' inbound connections.

Inputs: OpenAI-style chat-completion POSTs from the seats. Outputs: OpenRouter's
response body unchanged; one JSON line per forwarded call in --ledger (time, status,
model, latency, tokens, cost). GET /spend returns the running total; GET /healthz is ok.

Contract copied from the hosted sidecar (metta observatory_execution/job_runner/
llm_sidecar{,_app}.py, verified at metta 8b6042db): POST /v1/chat/completions (and
/api/v1/...); `stream: true` -> HTTP 400 (no streaming); caller policy fields
(provider, models, route, fallbacks, ...) stripped and `provider.require_parameters`
forced true, so a model that rejects a parameter fails here as it does hosted; the
running spend in the X-Coworld-Spend-Usd header. The hosted sidecar meters each seat
separately; this one serves every local seat, so its header is the run total. Seats
log their own per-call cost from the response body's `usage.cost`.
"""


import argparse
import json
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLER_POLICY_FIELDS = {
    "fallbacks", "metadata", "models", "plugins", "provider", "route",
    "service_tier", "session_id", "speed", "trace", "usage", "user",
}
ROUTES = {"/v1/chat/completions", "/api/v1/chat/completions"}

lock = threading.Lock()
spend = {"usd": 0.0, "calls": 0}


def make_handler(api_key, ledger_path, timeout):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body, extra=None):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            with lock:
                self.send_header("X-Coworld-Spend-Usd", f"{spend['usd']:.6f}")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/spend":
                with lock:
                    status = {"spend_usd": spend["usd"], "calls": spend["calls"]}
                return self._send(200, status)
            if self.path.startswith("/healthz"):
                return self._send(200, b"ok")
            self._send(404, {"error": {"message": "not found"}})

        def do_POST(self):
            if self.path not in ROUTES:
                return self._send(404, {"error": {"message": f"route {self.path} not served"}})
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if payload.get("stream") is True:
                return self._send(400, {"error": {"type": "invalid_request_error", "param": "stream",
                                                  "message": "streaming is not supported by this LLM sidecar"}})
            body = {k: v for k, v in payload.items() if k not in CALLER_POLICY_FIELDS}
            body["provider"] = {"require_parameters": True}
            request = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
            started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw, code = response.read(), response.status
            except urllib.error.HTTPError as error:
                raw, code = error.read(), error.code
            except (urllib.error.URLError, TimeoutError) as error:
                return self._send(502, {"error": {"message": f"upstream transport error: {error!r}"}})
            usage = {}
            try:
                usage = json.loads(raw).get("usage") or {}
            except ValueError:
                pass
            cost = float(usage.get("cost") or 0.0)
            with lock:
                spend["usd"] += cost
                spend["calls"] += 1
                if ledger_path:
                    with open(ledger_path, "a") as ledger:
                        ledger.write(json.dumps({
                            "t": time.time(), "status": code, "model": body.get("model"),
                            "latency_s": round(time.monotonic() - started, 2),
                            "prompt_tokens": usage.get("prompt_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                            "cost_usd": cost}) + "\n")
            self._send(code, raw)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9177)
    ap.add_argument("--ledger", help="append one JSON line per forwarded call")
    ap.add_argument("--timeout", type=float, default=60.0, help="upstream timeout, seconds (hosted: 60)")
    args = ap.parse_args()
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("set OPENROUTER_API_KEY in the environment first")
    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(api_key, args.ledger, args.timeout))
    print(f"local LLM sidecar on :{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
