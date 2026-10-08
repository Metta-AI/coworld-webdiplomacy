import os
import stat
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch

from adapter.artifacts import local_path, read_artifact, write_artifact


class ArtifactPaths(unittest.TestCase):
    def test_file_uri_decodes_once(self):
        path = Path('/tmp/episode results/percent%20name.json')
        self.assertEqual(local_path(path.as_uri()), path)

    def test_remote_scheme_rejected(self):
        with self.assertRaises(ValueError):
            local_path('https://example.com/results.json')

    def test_local_artifact_is_readable_by_the_runner_despite_boot_umask(self):
        # The local runner bind-mounts its workspace; a root-owned 0600 file is
        # unreadable by the non-root host user on Linux.
        with TemporaryDirectory() as directory:
            target = Path(directory) / 'results.json'
            previous = os.umask(0o077)
            try:
                write_artifact(target.as_uri(), b'{}', 'COGAME_RESULTS_METHOD')
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)

    def test_hosted_artifacts_use_http_methods(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"tokens": []}')

            def do_PUT(self):
                body = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.command, self.path, self.headers['Content-Type'], body))
                self.send_response(200)
                self.end_headers()

            do_POST = do_PUT

            def log_message(self, format, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            uri = f'http://127.0.0.1:{server.server_port}/artifact?signature=test'
            self.assertEqual(read_artifact(uri), b'{"tokens": []}')
            write_artifact(uri, b'{"scores": []}', 'COGAME_RESULTS_METHOD')
            with patch.dict('os.environ', COGAME_RESULTS_METHOD='POST'):
                write_artifact(uri, b'{"scores": []}', 'COGAME_RESULTS_METHOD')
            self.assertEqual(requests, [
                ('PUT', '/artifact?signature=test', 'application/json', b'{"scores": []}'),
                ('POST', '/artifact?signature=test', 'application/json', b'{"scores": []}'),
            ])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
