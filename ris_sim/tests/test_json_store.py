import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules import json_store


class TestJsonStore(unittest.TestCase):
    def test_atomic_write_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            json_store.write_json_atomic(path, {"nodes": [1]})
            self.assertEqual(json_store.load_json(path), {"nodes": [1]})

    def test_update_json_file_mutates_under_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"count": 1}))

            def mutate(data):
                data["count"] += 1
                return data

            updated = json_store.update_json_file(path, mutate)
            self.assertEqual(updated, {"count": 2})
            self.assertEqual(json.loads(path.read_text()), {"count": 2})


if __name__ == "__main__":
    unittest.main()
