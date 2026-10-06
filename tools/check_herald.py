"""Verify the documented seven-Herald episode's press, default holds and draw."""

import argparse
import json
from collections import Counter
from pathlib import Path


def check(directory):
    results = json.loads((directory / "results.json").read_text())
    frames = json.loads((directory / "replay").read_text())
    assert results["outcome"] == results["reason"] == "drawn", results
    assert int(results["final_state"]["turn"]) == 4, results["final_state"]
    final = frames[-1]
    greetings = [message for message in final["messages"]["messages"] if message["message"].startswith("Herald holds")]
    assert Counter((message["fromCountryID"], message["turn"]) for message in greetings) == Counter(
        {(country, turn): 1 for country in range(1, 8) for turn in range(5)}
    )
    orders = [order for phase in final["history"]["phases"] for order in phase["orders"]]
    assert len(orders) == 88 and all(order["type"] == "Hold" for order in orders)
    print(json.dumps(dict(passed=True, public_greetings=len(greetings), holds=len(orders), draw_year=1903)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    check(parser.parse_args().directory)
