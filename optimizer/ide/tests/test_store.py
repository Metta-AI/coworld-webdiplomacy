"""The on-disk store: chat, the agent's delivery cursor, cards and annotations."""

import os
import tempfile
import threading
import unittest

from webdip_ide import paths, store


class LabCase(unittest.TestCase):
    """A test with its own empty lab directory in `WEBDIP_LAB`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        previous = os.environ.get("WEBDIP_LAB")
        os.environ["WEBDIP_LAB"] = self._tmp.name
        self.addCleanup(
            lambda: os.environ.pop("WEBDIP_LAB") if previous is None else os.environ.update(WEBDIP_LAB=previous)
        )
        self.lab = paths.lab_dir()


class ChatTest(LabCase):
    def test_messages_are_numbered_and_filtered_by_after(self):
        first = store.post_message("user", "hello")
        second = store.post_message("agent", "hi", None)
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        self.assertEqual([m["text"] for m in store.messages(after=1)], ["hi"])
        self.assertNotIn("context", first)

    def test_context_is_kept(self):
        row = store.post_message("user", "look", {"episode": "ereq_1", "phase": 7})
        self.assertEqual(store.messages()[0]["context"], {"episode": "ereq_1", "phase": 7})
        self.assertEqual(row["context"]["phase"], 7)

    def test_unknown_sender_is_refused(self):
        with self.assertRaises(ValueError):
            store.post_message("robot", "x")

    def test_unread_is_delivered_once_and_only_user_messages(self):
        store.post_message("user", "one")
        store.post_message("agent", "reply")
        store.post_message("user", "two")
        self.assertTrue(store.has_unread_for_agent())
        self.assertEqual([m["text"] for m in store.take_unread_for_agent()], ["one", "two"])
        self.assertFalse(store.has_unread_for_agent())
        self.assertEqual(store.take_unread_for_agent(), [])
        store.post_message("user", "three")
        self.assertEqual([m["text"] for m in store.take_unread_for_agent()], ["three"])

    def test_agent_messages_alone_are_not_unread(self):
        store.post_message("agent", "talking to myself")
        self.assertFalse(store.has_unread_for_agent())

    def test_racing_consumers_get_each_message_once(self):
        for index in range(20):
            store.post_message("user", f"m{index}")
        taken = []
        barrier = threading.Barrier(8)

        def consume():
            barrier.wait()
            taken.extend(m["seq"] for m in store.take_unread_for_agent())

        threads = [threading.Thread(target=consume) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(taken), list(range(1, 21)))

    def test_concurrent_posts_get_distinct_sequence_numbers(self):
        threads = [threading.Thread(target=store.post_message, args=("user", f"m{i}")) for i in range(25)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(m["seq"] for m in store.messages()), list(range(1, 26)))


class PresenceTest(LabCase):
    def test_agent_seen(self):
        self.assertIsNone(store.agent_seen())
        store.touch_agent_seen()
        self.assertIsInstance(store.agent_seen(), float)


class FollowedPolicyTest(LabCase):
    def test_recorded_and_read_back(self):
        self.assertEqual(store.followed_policy(), "")
        store.set_followed_policy("my-policy")
        self.assertEqual(store.followed_policy(), "my-policy")


class CardTest(LabCase):
    def test_post_and_list(self):
        store.post_card("idea", "Try X", "**body**", "/replays/e1?phase=2")
        store.post_card("note", "Second")
        self.assertEqual([c["title"] for c in store.cards(after=1)], ["Second"])
        self.assertEqual(store.cards()[0]["link"], "/replays/e1?phase=2")

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            store.post_card("poster", "x")


class AnnotationTest(LabCase):
    def test_add_list_delete(self):
        row = store.add_annotation("ereq_1", "user", "bad move", tag="blunder", phase=3, power="FRANCE")
        store.add_annotation("ereq_2", "agent", "noted")
        self.assertEqual(store.annotations("ereq_1")[0]["text"], "bad move")
        self.assertEqual(sorted(store.all_annotations()), ["ereq_1", "ereq_2"])
        self.assertTrue((self.lab / "annotations" / "ereq_1.json").exists())
        self.assertTrue(store.delete_annotation("ereq_1", row["id"]))
        self.assertFalse(store.delete_annotation("ereq_1", row["id"]))
        self.assertEqual(store.annotations("ereq_1"), [])

    def test_no_lock_file_appears_among_the_tracked_notes(self):
        store.add_annotation("ereq_1", "user", "left SWE open", tag="blunder", phase=3)
        self.assertEqual([p.name for p in paths.annotations_dir().iterdir()], ["ereq_1.json"])
        self.assertTrue((paths.state_dir() / "ereq_1.json.lock").exists())

    def test_bad_values_are_refused(self):
        with self.assertRaises(ValueError):
            store.add_annotation("ereq_1", "user", "x", tag="rant")
        with self.assertRaises(ValueError):
            store.add_annotation("../escape", "user", "x")
        with self.assertRaises(ValueError):
            store.add_annotation("ereq_1", "nobody", "x")


if __name__ == "__main__":
    unittest.main()
