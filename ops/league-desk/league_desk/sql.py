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


def query(kind, ids, after=None):
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
