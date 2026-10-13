"""Cached version choices and explicit time-window bounds."""

RANGES = {"24h": (86400, "24 hours"), "7d": (7 * 86400, "7 days"), "30d": (30 * 86400, "30 days"),
          "all": (None, "All retained history")}


def version_choices(snapshot):
    choices = {r["id"]: r["version"] for r in
               (snapshot.get(("versions", "all"), {}).get("data") or {}).get("rows", [])}
    for (name, _), state in snapshot.items():
        if name == "episodes" and state.get("data"):
            choices.update({g["coworld_id"]: g["version"] for g in state["data"]["rows"] if g["coworld_id"]})
    canonical = (snapshot.get(("canonical", "all"), {}).get("data") or {})
    if canonical:
        choices[canonical["id"]] = canonical["version"]
    return choices
