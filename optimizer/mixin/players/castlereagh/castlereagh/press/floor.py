"""Press part (b), the order floor: legal orders saved before the LLM is consulted.

Every press movement phase starts by saving `default_floor`'s orders (not Ready). The LLM
can replace them with `commit_orders`, but it never sits on the path that produces legal
orders: a failed, slow or misconfigured model leaves the seat playing the floor, which is
exactly what `CASTLEREAGH_POLICY=search` would play in that position.

To try a different floor, replace `default_floor` with any function of the same shape.
"""

from castlereagh.webdip_api import order_difference


def default_floor(service, rng_key):
    """The Default search with no press policy. Returns (orders, report, trace)."""
    return service.search(None, rng_key=rng_key)


def save_orders(api, context, orders, ready):
    """Save orders and diff what upstream kept. Upstream answers 200 while silently dropping
    invalid orders, so the returned difference (`missing`) is the real acceptance check."""
    saved = api.orders(context, orders, ready=ready)
    try:
        return order_difference(orders, saved, len(context["orders"]["orders"]))
    except (TypeError, ValueError, KeyError):
        # Upstream can echo a saved build/destroy with a null territory; the orders are saved,
        # only the comparison fails. Record it instead of losing the decision log.
        return {"missing": [], "unexpected": [], "diff_error": True}
