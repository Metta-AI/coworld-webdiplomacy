"""Standalone Chromium replay acceptance: no game container, only static HTTP."""

import argparse
import gzip
import json
import shutil
import subprocess
import threading
import zlib
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from coworld.replay_viewer import STATIC_REPLAY_BUNDLE_CSP
from playwright.sync_api import expect, sync_playwright


def run(replays, directory=Path("tmp/p5-static-replay")):
    root = Path("build/static-replay-viewer").resolve()
    hook = Path("tools/build_replay_viewer.sh").resolve()
    subprocess.run([str(hook), str(root)], check=True)
    (root / "stale-sentinel").touch()
    subprocess.run([str(hook), str(root)], check=True)
    assert not (root / "stale-sentinel").exists()
    files = list(root.rglob("*"))
    assert all(file.is_file() and not file.is_symlink() for file in files)
    assert len(files) <= 4096 and sum(file.stat().st_size for file in files) < 256 * 1024**2
    directory.mkdir(exist_ok=True)
    # Keep replay fixtures outside the source bundle.
    bundle = directory / "assets" / "content-hash"
    bundle.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "viewer.js", "smallmap.png"):
        shutil.copyfile(root / name, bundle / name)
    (directory / "corrupt").write_text("{bad")
    (directory / "incompatible").write_text("[{}]")
    damaged = json.loads(replays[0].read_text())
    damaged[0]["map"] = {"turn": -1, "png": "data:image/png;base64,AAAA"}
    (directory / "broken-map").write_text(json.dumps(damaged))
    (directory / "host.html").write_text("""<!doctype html><script>
      window.events=[]; addEventListener('message', e => {
        if(e.data?.src==='coworld-replay') {
          const frame=document.querySelector('iframe').contentDocument;
          events.push({...e.data, rendered: frame.querySelector('#phase').textContent !== 'Loading game state…',
            imageLoaded: frame.querySelector('#background').getAttribute('href') !== null});
        }
      });</script><iframe style="width:100%;height:900px"></iframe>""")

    class Handler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Security-Policy", STATIC_REPLAY_BUNDLE_CSP)
            super().end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    evidence = []
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        artifact_base = f"http://localhost:{server.server_port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if "Content Security Policy" in message.text else None,
            )
            for number, replay in enumerate(replays):
                content = replay.read_bytes()
                frames = json.loads(content)
                assert "private-press-real-engine-sentinel" not in content.decode()
                assert "p5-private-sentinel" not in content.decode()
                for encoding, encoded, separator in (
                    ("plain", content, "#"),
                    ("gzip", gzip.compress(content), "?"),
                    ("zlib", zlib.compress(content), "#"),
                ):
                    name = f"fixture-{number}-{encoding}"
                    (directory / name).write_bytes(encoded)
                    page.goto(base + "/host.html")
                    page.locator("iframe").evaluate(
                        "(el, url) => el.src = url",
                        base
                        + "/assets/content-hash/index.html"
                        + separator
                        + "replay="
                        + quote(artifact_base + "/" + name, safe=""),
                    )
                    page.wait_for_function("() => events.some(e => e.type === 'ready')")
                    events = page.evaluate("events")
                    ready = next(event for event in events if event["type"] == "ready")
                    assert ready["rendered"] and ready["imageLoaded"], events
                    assert not any(event["type"] == "error" for event in events), events
                    view = page.frame_locator("iframe")
                    expect(view.locator("#play")).to_have_text("Pause")
                    view.locator("#play").click()
                    expect(view.locator("#play")).to_have_text("Play")
                    for i, frame in enumerate(frames):
                        view.locator("#timeline button").nth(i).click()
                        expect(view.locator("#counter")).to_have_text(f"Phase {i + 1} of {len(frames)}")
                        if frame["game"]["phase"] == "Pre-game":
                            expect(view.locator("#outcome")).to_have_text(
                                "Starting position — units appear in Spring 1901"
                            )
                        board = frame["game"]
                        if not board["territories"]:
                            board = next(
                                (old["game"] for old in reversed(frames[:i]) if old["game"]["territories"]), board
                            )
                        expect(view.locator("#units > g")).to_have_count(len(board["units"]))
                        phases = frame["history"]["phases"]
                        expect(view.locator("#orders li")).to_have_count(len(phases[-1]["orders"]) if phases else 0)
                        if encoding == "plain":
                            view.locator("#map").screenshot(path=str(directory / f"map-{number}-{i}.png"))
                        if frame.get("map"):
                            assert view.locator("#season-map").get_attribute("src") == frame["map"]["png"]
                    view.locator("#loop").uncheck()
                    view.locator("#speed").select_option("600")
                    view.locator("#play").click()
                    expect(view.locator("#play")).to_have_text("Play", timeout=3000)
                    view.locator("#loop").check()
                    view.locator("#play").click()
                    expect(view.locator("#counter")).to_have_text(f"Phase 1 of {len(frames)}", timeout=3000)
                    view.locator("#play").click()
                    page.set_viewport_size({"width": 500, "height": 850})
                    expect(view.locator("#map")).to_be_visible()
                    page.screenshot(path=str(directory / f"replay-{number}-{encoding}.png"))
                    page.set_viewport_size({"width": 1200, "height": 1000})
                    evidence.append(dict(replay=str(replay), encoding=encoding, frames=len(frames), ready=ready))
            for suffix in (
                "",
                "#replay=" + quote(base + "/missing", safe=""),
                "#replay=" + quote(base + "/corrupt", safe=""),
                "#replay=" + quote(base + "/incompatible", safe=""),
                "#replay=" + quote(base + "/broken-map", safe=""),
            ):
                page.goto(base + "/host.html")
                page.locator("iframe").evaluate(
                    "(el,url) => el.src=url", base + "/assets/content-hash/index.html" + suffix
                )
                page.wait_for_function("() => events.some(e => e.type === 'error')")
                assert not any(event["type"] == "ready" for event in page.evaluate("events"))
                expect(page.frame_locator("iframe").get_by_role("alert")).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    (directory / "evidence.json").write_text(json.dumps(evidence, indent=2))
    print(
        json.dumps(
            dict(
                passed=True,
                replay_loads=len(evidence),
                error_cases=5,
                bundle_bytes=sum(file.stat().st_size for file in files),
            )
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replays", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/p5-static-replay"))
    args = parser.parse_args()
    run(args.replays, args.output_dir)
