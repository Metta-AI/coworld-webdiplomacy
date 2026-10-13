import signal
from unittest.mock import Mock, patch

from helpers import DeskTest

from league_desk.cli import main


class CliTests(DeskTest):
    def test_no_collector_never_spawns_or_logs_in(self):
        with patch("league_desk.cli.runtime_dir", return_value=self.store.directory), \
             patch("uvicorn.run") as run, patch("subprocess.Popen") as spawn:
            self.assertEqual(main(["serve", "--no-collector"]), 0)
            spawn.assert_not_called()
            self.assertEqual(run.call_args.kwargs["host"], "127.0.0.1")

    def test_only_owned_child_terminated_on_server_error(self):
        child = Mock()
        child.poll.return_value = None
        with patch("league_desk.cli.runtime_dir", return_value=self.store.directory), \
             patch("uvicorn.run", side_effect=RuntimeError("bind failed")), \
             patch("subprocess.Popen", return_value=child) as spawn:
            with self.assertRaisesRegex(RuntimeError, "bind failed"):
                main(["serve"])
        self.assertEqual(spawn.call_args.args[0][-2:], ["league_desk", "collect"])
        child.terminate.assert_called_once()
        child.wait.assert_called_once()

    def test_already_exited_child_is_not_signalled(self):
        child = Mock()
        child.poll.return_value = 1
        with patch("league_desk.cli.runtime_dir", return_value=self.store.directory), \
             patch("uvicorn.run"), patch("subprocess.Popen", return_value=child):
            main(["serve"])
        child.terminate.assert_not_called()

    def test_replayed_sigterm_unwinds_and_stops_owned_child(self):
        child = Mock()
        child.poll.return_value = None
        previous = signal.getsignal(signal.SIGTERM)

        def replay(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        with patch("league_desk.cli.runtime_dir", return_value=self.store.directory), \
             patch("uvicorn.run", side_effect=replay), patch("subprocess.Popen", return_value=child):
            with self.assertRaises(SystemExit):
                main(["serve"])
        child.terminate.assert_called_once()
        child.wait.assert_called_once()
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)
