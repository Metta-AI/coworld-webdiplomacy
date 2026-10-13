"""Local alert identity follows changed facts, independently of display wording."""
import hashlib
import json
from collections import defaultdict

from .config import MODEL_ERROR_RATE, MODEL_MIN_CALLS


def alert(message, scope, kind, facts):
    encoded = json.dumps([scope, kind, facts], sort_keys=True, separators=(",", ":"))
    return {"message": message, "fingerprint": hashlib.sha256(encoded.encode()).hexdigest()}


def model_alerts(provider, attempts, scope):
    result = []
    for rows, numerator, denominator, kind, description in (
            (provider, "failed", "calls", "provider", "provider calls failed"),
            (attempts, "not_ok", "attempts", "attempt", "attempts not OK")):
        policies = defaultdict(lambda: [0, 0, None])
        for row in rows:
            group = policies[row["model"], row["policy_version_id"]]
            group[0] += row[numerator]
            group[1] += row[denominator]
            group[2] = max((d for d in (group[2], row.get("failure_day")) if d), default=None)
        affected = defaultdict(list)
        for (model, policy), (failed, total, latest) in policies.items():
            if total >= MODEL_MIN_CALLS and failed / total > MODEL_ERROR_RATE:
                affected[model].append((policy, failed, total, latest))
        for model, values in sorted(affected.items()):
            failed, total = sum(v[1] for v in values), sum(v[2] for v in values)
            facts = [model, sorted(v[0] for v in values), max((v[3] for v in values if v[3]), default=None)]
            result.append(alert(f"{model or 'Unknown model'}: {failed}/{total} {description} across "
                                f"{len(values)} affected policy versions in this league.", scope, kind, facts))
    return result


def prepare_alerts(messages, scope, versions, stale_sources, dismissed):
    active, hidden, seen = [], [], set()
    for item in messages:
        if isinstance(item, str):
            if "mixed-version inputs" in item:
                item = alert(item, scope, "mixed-versions", sorted(versions))
            elif "sources" in item and ("stale" in item or "incomplete" in item):
                item = alert("Sources failed, stale or incomplete; inspect panel coverage.", scope,
                             "stale-sources", sorted(stale_sources))
            else:
                item = alert(item, scope, "reading", item)
        if item["fingerprint"] in seen:
            continue
        seen.add(item["fingerprint"])
        (hidden if item["fingerprint"] in dismissed else active).append(item)
    return active, hidden
