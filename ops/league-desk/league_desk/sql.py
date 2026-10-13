"""Fixed, scoped SELECT templates. No browser or caller can submit SQL text."""

import re
from uuid import UUID

from .api import ApiError
from .config import SQL_PAGE_SIZE

OVERRIDES = ("end_year", "phase_minutes", "retreat_build_minutes", "press", "seed", "render_maps")


def identifier(value, prefix):
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ApiError("Invalid SQL scope identifier")
    try:
        return str(UUID(value[len(prefix) :]))
    except ValueError:
        raise ApiError("Invalid SQL scope identifier") from None


def query(kind, ids, after=None, *, start=None, end=None):
    if kind in ATTRIBUTION_COLUMNS:
        return attribution_query(kind, ids, after, start, end)
    if not ids or len(ids) > 50 or kind not in ("seats", "overrides"):
        raise ApiError("Invalid SQL scope")
    prefix = "ereq_" if kind == "seats" else "xreq_"
    values = sorted({identifier(value, prefix) for value in ids})
    if kind == "seats":
        literals = ",".join(f"'{value}'::uuid" for value in values)
        continuation = ""
        if after is not None:
            last = identifier("ereq_" + after[0], "ereq_")
            if not re.fullmatch(r"[0-9]{1,3}", after[1]):
                raise ApiError("Invalid SQL slot cursor")
            continuation = f" AND (episode_request_id, slot) > ('{last}'::uuid, '{after[1]}')"
        return (
            "SELECT episode_request_id::text AS episode, slot, SUM(invocations)::bigint AS calls, "
            "SUM(estimated_cost_usd) AS estimated, SUM(spend_limit_rejections)::bigint AS rejections "
            f"FROM episode_llm_usage WHERE episode_request_id IN ({literals}) AND role = 'player'"
            f"{continuation} GROUP BY episode_request_id, slot ORDER BY episode_request_id, slot "
            f"LIMIT {SQL_PAGE_SIZE}"
        )
    literals = ",".join(f"'xreq_{value}'" for value in values)
    fields = ", ".join(f"request_spec->'game_config_overrides'->'{key}' AS {key}" for key in OVERRIDES)
    continuation = ""
    if after is not None:
        last = identifier(after[0], "xreq_")
        continuation = f" AND experience_request_id > 'xreq_{last}'"
    return (
        f"SELECT experience_request_id AS request, {fields} FROM experience_requests "
        f"WHERE experience_request_id IN ({literals}){continuation} "
        f"ORDER BY experience_request_id LIMIT {SQL_PAGE_SIZE}"
    )


def select_rows(api, kind, ids):
    """Aggregate buckets/providers once at seat grain; replace snapshots, never add poll totals."""
    if not ids:
        return []
    table = "episode_llm_usage" if kind == "seats" else "experience_requests"
    fields = {c["name"] for c in api.json(f"/sql/tables/{table}/schema")["columns"]}
    required = (
        {
            "episode_request_id",
            "slot",
            "bucket_start",
            "source_system",
            "role",
            "invocations",
            "estimated_cost_usd",
            "spend_limit_rejections",
        }
        if kind == "seats"
        else {"experience_request_id", "request_spec"}
    )
    if not required <= fields:
        raise ApiError("SQL schema lacks required fields")
    rows, seen, after = [], set(), None
    for _ in range(10):
        try:
            payload = api.select(kind, ids, after)
        except ApiError as error:
            if str(error) == "API returned HTTP 408" and len(ids) > 1:
                middle = len(ids) // 2
                return select_rows(api, kind, ids[:middle]) + select_rows(api, kind, ids[middle:])
            raise
        expected = (
            ["episode", "slot", "calls", "estimated", "rejections"] if kind == "seats" else ["request", *OVERRIDES]
        )
        if payload["columns"] != expected:
            raise ApiError("Unexpected SQL columns")
        for values in payload["rows"]:
            if len(values) != len(expected):
                raise ApiError("Unexpected SQL row width")
            row = dict(zip(expected, values, strict=True))
            key = (row["episode"], row["slot"]) if kind == "seats" else (row["request"],)
            scoped_id = "ereq_" + key[0] if kind == "seats" else key[0]
            if scoped_id not in ids or key in seen:
                raise ApiError("Unscoped or repeated SQL row")
            seen.add(key)
            rows.append(row)
            after = key
        if len(payload["rows"]) < SQL_PAGE_SIZE:
            return rows
    raise ApiError("SQL pagination exceeded collection bound")


ATTRIBUTION_COLUMNS = {
    "daily_spend": ["league_id", "source", "day", "compute", "llm", "week_compute", "week_llm"],
    "seat_models": ["episode", "slot", "model", "player_id", "player", "policy_id", "policy", "policy_version_id",
                    "version", "created_at", "coworld_id", "calls", "failed", "usd", "failure_day"],
    "attempts": ["policy_version_id", "model", "attempts", "not_ok", "refused", "failure_day"],
}


def attribution_query(kind, ids, after, start, end):
    """Three league-scoped templates; timestamps are bounded integer epoch seconds."""
    if kind not in ATTRIBUTION_COLUMNS or len(ids) != 1:
        raise ApiError("Invalid attribution scope")
    league = "league_" + identifier(ids[0], "league_")
    if (type(start) is not int or type(end) is not int or not 0 < start < end or end - start > 31 * 86400):
        raise ApiError("Invalid SQL time window")
    lo, hi = f"to_timestamp({start})", f"to_timestamp({end})"
    if kind == "daily_spend":
        if after is not None:
            raise ApiError("Daily aggregates do not accept a cursor")
        return f"""SELECT league_id, source,
          (bucket_start AT TIME ZONE 'America/Los_Angeles')::date::text AS day,
          COALESCE(SUM(cost_usd) FILTER (WHERE usage_kind = 'ecs_compute'),0) AS compute,
          COALESCE(SUM(COALESCE(estimated_cost_usd,cost_usd))
            FILTER (WHERE usage_kind IN ('llm','llm_bedrock')),0) AS llm,
          COALESCE(SUM(cost_usd) FILTER (WHERE usage_kind = 'ecs_compute'
            AND bucket_start >= {hi} - interval '7 days'),0) AS week_compute,
          COALESCE(SUM(COALESCE(estimated_cost_usd,cost_usd)) FILTER
            (WHERE usage_kind IN ('llm','llm_bedrock') AND bucket_start >= {hi} - interval '7 days'),0) AS week_llm
        FROM usage_records WHERE league_id = '{league}' AND bucket_start >= {lo} AND bucket_start < {hi}
          AND usage_kind IN ('ecs_compute','llm','llm_bedrock')
          AND source IN ('tournament','xp_request','coworld_persistent')
        GROUP BY 1,2,3 ORDER BY 1,3,2 LIMIT {SQL_PAGE_SIZE}"""
    continuation = ""
    if after is not None:
        if not isinstance(after, (tuple, list)) or len(after) != 3:
            raise ApiError("Invalid attribution cursor")
        episode = identifier("ereq_" + str(after[0]), "ereq_")
        slot, model = after[1:]
        if type(slot) is not int or not 0 <= slot <= 6 or not isinstance(model, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:/@+ -]{0,200}", model):
            raise ApiError("Invalid attribution cursor")
        continuation = f"WHERE (episode,slot,model COLLATE \"C\") > ('{episode}',{slot},'{model}' COLLATE \"C\")"
    seats = f"""SELECT er.id AS er_id, erp.position AS slot, erp.policy_version_id,
          er.created_at, er.coworld_id
        FROM episode_requests er JOIN rounds r ON r.id=er.round_id
        JOIN divisions d ON d.id=r.division_id JOIN leagues l ON l.id=d.league_id
        JOIN episode_request_policies erp ON erp.episode_request_id=er.id
        WHERE l.league_id='{league}' AND er.created_at >= {lo} AND er.created_at < {hi}"""
    if kind == "seat_models":
        body = f"""WITH seat AS ({seats}), ev AS (
          SELECT (e.request_metadata->>'episode_request_id')::uuid AS er_id,
            (e.request_metadata->>'slot')::int AS slot, COALESCE(e.resolved_model,'') AS model,
            COUNT(*)::bigint AS calls, COUNT(*) FILTER (WHERE e.status <> 'completed')::bigint AS failed,
            COALESCE(SUM(e.billed_cost_usd),0) AS usd,
            (MAX(e.timestamp) FILTER (WHERE e.status <> 'completed')
              AT TIME ZONE 'America/Los_Angeles')::date::text AS failure_day
          FROM llm_provider_events e WHERE e.credited_id='{league}'
            AND e.timestamp >= {lo} - interval '1 day' AND e.timestamp < {hi}
            AND e.request_metadata->>'role'='player' GROUP BY 1,2,3
        ), result AS (
          SELECT seat.er_id::text AS episode, seat.slot, COALESCE(ev.model,'') AS model,
            pl.player_id, pl.name AS player, pv.policy_id::text, p.name AS policy,
            pv.id::text AS policy_version_id, pv.version, extract(epoch FROM seat.created_at)::float8 AS created_at,
            seat.coworld_id::text, COALESCE(ev.calls,0)::bigint AS calls,
            COALESCE(ev.failed,0)::bigint AS failed, COALESCE(ev.usd,0) AS usd, ev.failure_day
          FROM seat LEFT JOIN ev ON ev.er_id=seat.er_id AND ev.slot=seat.slot
          JOIN policy_versions pv ON pv.id=seat.policy_version_id JOIN policies p ON p.id=pv.policy_id
          LEFT JOIN players pl ON pl.player_id=pv.player_id)"""
    else:
        body = f"""WITH er AS (
          SELECT er.id, era.job_request_id::text AS jr
          FROM episode_requests er JOIN episode_request_attempts era ON era.episode_request_id=er.id
          JOIN rounds r ON r.id=er.round_id JOIN divisions d ON d.id=r.division_id
          JOIN leagues l ON l.id=d.league_id
          WHERE l.league_id='{league}' AND er.created_at >= {lo} AND er.created_at < {hi}
        ), at AS (
          SELECT er.id AS er_id, (a.request_metadata->>'slot')::int AS slot,
            COALESCE(a.requested_model,'') AS model, a.ok, a.policy_result, a.timestamp
          FROM er JOIN llm_attempt_events a
            ON a.request_metadata->>'job_request_id'=er.jr AND a.source='coworld_episode'
          WHERE a.request_metadata->>'role'='player'
        ), result AS (
          SELECT erp.policy_version_id::text, at.model,
            COUNT(*)::bigint AS attempts, COUNT(*) FILTER (WHERE NOT at.ok)::bigint AS not_ok,
            COUNT(*) FILTER (WHERE at.policy_result <> 'accepted')::bigint AS refused,
            (MAX(at.timestamp) FILTER (WHERE NOT at.ok)
              AT TIME ZONE 'America/Los_Angeles')::date::text AS failure_day
          FROM at JOIN episode_request_policies erp ON erp.episode_request_id=at.er_id AND erp.position=at.slot
          GROUP BY 1,2)"""
        if after is not None:
            raise ApiError("Attempt aggregates do not accept a cursor")
        return body + f' SELECT * FROM result ORDER BY policy_version_id,model LIMIT {SQL_PAGE_SIZE}'
    return (body + f' SELECT * FROM result {continuation} ORDER BY episode,slot,model COLLATE "C" '
            f"LIMIT {SQL_PAGE_SIZE}")


def attribution_rows(api, kind, league, start, end):
    """A full aggregate page or an unfinished keyset walk is never treated as complete."""
    rows, seen, after = [], set(), None
    for _ in range(20):
        try:
            payload = api.select(kind, [league], after, start=start, end=end)
        except ApiError as error:
            if kind != "attempts" or str(error) != "API returned HTTP 408" or end-start <= 86400:
                raise
            # Split disjoint game-creation cohorts, not event time: every attempt stays with its game.
            middle = (start+end)//2
            parts = (attribution_rows(api, kind, league, start, middle) +
                     attribution_rows(api, kind, league, middle, end))
            merged = {}
            for row in parts:
                key = row["policy_version_id"], row["model"]
                if key not in merged:
                    merged[key] = dict(row)
                else:
                    for field in ("attempts", "not_ok", "refused"):
                        merged[key][field] += row[field]
                    merged[key]["failure_day"] = max(
                        (d for d in (merged[key]["failure_day"], row["failure_day"]) if d), default=None)
            if len(merged) >= SQL_PAGE_SIZE:
                raise ApiError("Attribution SQL exceeded collection bound")
            return list(merged.values())
        columns = ATTRIBUTION_COLUMNS[kind]
        if payload["columns"] != columns or len(payload["rows"]) > SQL_PAGE_SIZE:
            raise ApiError("Unexpected attribution SQL shape")
        for values in payload["rows"]:
            if len(values) != len(columns):
                raise ApiError("Unexpected attribution SQL width")
            row = dict(zip(columns, values, strict=True))
            if kind == "attempts" and any(type(row[k]) is not int or row[k] < 0
                                          for k in ("attempts", "not_ok", "refused")):
                raise ApiError("Invalid attempt SQL counts")
            key = ((row["league_id"], row["day"], row["source"]) if kind == "daily_spend" else
                   (row["policy_version_id"], row["model"]) if kind == "attempts" else
                   (row["episode"], row["slot"], row["model"]))
            if key in seen or (kind == "daily_spend" and row["league_id"] != league):
                raise ApiError("Repeated or unscoped attribution row")
            seen.add(key)
            rows.append(row)
            after = key
        if len(payload["rows"]) < SQL_PAGE_SIZE:
            return rows
        if kind in ("daily_spend", "attempts"):
            break
    raise ApiError("Attribution SQL exceeded collection bound")
