"""A realistic large-surface online-shopping environment ("shop").

Motivation (fairness of the evaluation): HATEOAS's benefits show on APIs with a *large,
real* surface area, not on toy tool sets padded with no-op distractors. This environment
replicates the tool surface of a real e-commerce service (authentication, profile,
catalog, cart, checkout, order lifecycle, refunds, reviews, subscriptions, support) with
a seeded population of products, users, and orders, and a policy document of the kind a
human support agent would be given (cf. tau-bench's retail wiki). Every tool is genuine:
it has a real guard and a real effect on the database -- nothing is a dummy.

Hardness: tasks are multi-constraint and reference orders by content ("the order with
the espresso machine"), not by id, so the agent must inspect state before acting; several
tasks require correct *ordering* of actions (modifying an order locks it, so the address
must be changed first), and several are traps whose correct outcome is to refuse.

The same policy text handed to the baselines is the exact source of the guards, so the
comparison is fair: HyperMCP receives no domain knowledge that the baselines lack.
"""
from __future__ import annotations
import random
from ..core import State, Affordance, Env, Task, AgentContext

TODAY = 400                # day index of "now"; order timestamps are day indices
RETURN_WINDOW = 30         # days after delivery in which return/exchange is allowed

_CATEGORIES = {
    "apparel": ["T-Shirt", "Hoodie", "Running Shoes", "Rain Jacket", "Wool Socks"],
    "electronics": ["Headphones", "Desk Lamp", "Espresso Machine", "Smart Speaker",
                    "Mechanical Keyboard"],
    "home": ["Ceramic Mug", "Throw Blanket", "Scented Candle", "Cutting Board"],
    "outdoors": ["Water Bottle", "Trail Backpack", "Camping Stove"],
    "media": ["Cookbook", "Sci-Fi Novel", "Yoga Mat"],
}
_ADJECTIVES = ["Classic", "Premium", "Eco", "Compact", "Deluxe", "Sport", "Urban",
               "Vintage", "Pro", "Ultra"]
_COLORS = ["Black", "White", "Navy", "Forest", "Crimson"]
_SIZES = ["S", "M", "L", "XL"]
_FIRST = ["Emma", "Liam", "Mia", "Noah", "Lena", "Luca", "Nina", "Jonas", "Sofia", "David"]
_LAST = ["Berger", "Keller", "Meier", "Schmid", "Weber", "Huber", "Frei", "Baumann"]


# --------------------------------------------------------------------------- #
# Seeded world generation (deterministic).
# --------------------------------------------------------------------------- #
def _gen_products(rng: random.Random) -> dict:
    products = {}
    pid = 1
    for cat, nouns in _CATEGORIES.items():
        for noun in nouns:
            for adj in _ADJECTIVES:
                for color in (_COLORS if cat == "apparel" else [None]):
                    name = f"{adj} {color + ' ' if color else ''}{noun}"
                    products[f"P{pid:04d}"] = {
                        "name": name, "category": cat,
                        "price": round(rng.uniform(9, 349), 2),
                        "sizes": _SIZES if cat == "apparel" else [],
                        "in_stock": rng.random() > 0.08,
                    }
                    pid += 1
    return products


def _gen_users_and_orders(rng: random.Random, products: dict) -> tuple[dict, dict]:
    users, orders = {}, {}
    pids = sorted(products)
    oid = 1
    for uid_n in range(1, 241):
        uid = f"U{uid_n:04d}"
        first = rng.choice(_FIRST)
        last = rng.choice(_LAST)
        users[uid] = {
            "first": first, "last": last,
            "email": f"{first.lower()}.{last.lower()}{uid_n}@mail.com",
            "zip": f"{rng.randint(1000, 9999)}",
            "tier": rng.choice(["basic", "basic", "silver", "gold"]),
            "addresses": {"A1": "home address", "A2": "office address"},
            "payment_methods": {"PM1": "Visa **42"} if rng.random() < 0.5
                               else {"PM1": "Visa **42", "PM2": "Mastercard **07"},
            "gift_card": round(rng.choice([0, 0, 25, 50]), 2),
            "orders": [],
            "subscriptions": {},
        }
        for _ in range(rng.randint(1, 4)):
            wid = f"W{oid:05d}"
            status = rng.choice(["pending", "shipped", "delivered", "delivered",
                                 "cancelled"])
            delivered = TODAY - rng.randint(1, 120) if status == "delivered" else None
            orders[wid] = {
                "user_id": uid, "status": status,
                "items": [{"product_id": (p := rng.choice(pids)),
                           "name": products[p]["name"], "qty": rng.randint(1, 2),
                           "size": rng.choice(_SIZES) if products[p]["sizes"] else None}
                          for _ in range(rng.randint(1, 3))],
                "address_id": "A1", "payment_id": "PM1",
                "delivered_day": delivered, "modified": False,
            }
            users[uid]["orders"].append(wid)
            oid += 1
    return users, orders


def _place_test_user(users: dict, orders: dict, products: dict) -> None:
    """Deterministic protagonist + hand-placed orders that the tasks reference."""
    products["P9001"] = {"name": "Pro Black Hoodie", "category": "apparel",
                         "price": 89.0, "sizes": _SIZES, "in_stock": True}
    uid = "U0001"
    users[uid].update({
        "first": "Emma", "last": "Berger", "email": "emma.berger@mail.com",
        "zip": "9000", "tier": "basic", "gift_card": 25.0,
        "payment_methods": {"PM1": "Mastercard **07"},   # single method (delete trap)
        "subscriptions": {"S1": {"name": "coffee beans, monthly", "status": "paused"}},
    })
    hand = {
        "W90001": dict(status="pending", items=[{"product_id": "P0061",
                       "name": "Classic Espresso Machine", "qty": 1, "size": None}]),
        "W90002": dict(status="delivered", delivered_day=TODAY - 8,
                       items=[{"product_id": "P0051", "name": "Classic Headphones",
                               "qty": 1, "size": None}]),
        "W90003": dict(status="delivered", delivered_day=TODAY - 45,
                       items=[{"product_id": "P0011", "name": "Classic Running Shoes",
                               "qty": 1, "size": None}]),
        "W90004": dict(status="delivered", delivered_day=TODAY - 5,
                       items=[{"product_id": "P0001", "name": "Classic Black T-Shirt",
                               "qty": 1, "size": "M"}]),
        "W90005": dict(status="shipped", items=[{"product_id": "P0056",
                       "name": "Classic Desk Lamp", "qty": 1, "size": None}]),
        "W90006": dict(status="pending", items=[{"product_id": "P0096",
                       "name": "Classic Cookbook", "qty": 1, "size": None}]),
    }
    for wid, o in hand.items():
        orders[wid] = {"user_id": uid, "address_id": "A1", "payment_id": "PM1",
                       "delivered_day": None, "modified": False, **o}
    users[uid]["orders"] = list(hand)


def _seed_db() -> dict:
    rng = random.Random(7)
    products = _gen_products(rng)
    users, orders = _gen_users_and_orders(rng, products)
    _place_test_user(users, orders, products)
    return {"today": TODAY, "products": products, "users": users, "orders": orders,
            "carts": {}}


# --------------------------------------------------------------------------- #
# Guard helpers.
# --------------------------------------------------------------------------- #
def _auth(s: State) -> bool:
    return s.authenticated_user is not None


def _me(s: State) -> dict:
    return s.db["users"][s.authenticated_user]


def _owns(s: State, oid) -> bool:
    if not _auth(s) or oid is None:
        return False
    o = s.db["orders"].get(oid)
    return o is not None and o["user_id"] == s.authenticated_user


def _order(s: State, oid) -> dict:
    return s.db["orders"][oid]


def _in_return_window(s: State, oid) -> bool:
    o = s.db["orders"].get(oid, {})
    return (o.get("status") == "delivered" and o.get("delivered_day") is not None
            and s.db["today"] - o["delivered_day"] <= RETURN_WINDOW)


def _cart(s: State) -> list:
    return s.db["carts"].setdefault(s.authenticated_user, [])


# --------------------------------------------------------------------------- #
# Effects.
# --------------------------------------------------------------------------- #
def _find_by_email(s, a):
    for uid, u in s.db["users"].items():
        if u["email"].lower() == str(a.get("email", "")).lower():
            s.authenticated_user = uid
            return f"authenticated {u['first']} {u['last']} ({uid}), tier={u['tier']}"
    return "no user with that email"


def _find_by_name_zip(s, a):
    for uid, u in s.db["users"].items():
        if (u["first"].lower() == str(a.get("first", "")).lower()
                and u["last"].lower() == str(a.get("last", "")).lower()
                and u["zip"] == str(a.get("zip", ""))):
            s.authenticated_user = uid
            return f"authenticated {u['first']} {u['last']} ({uid}), tier={u['tier']}"
    return "no matching user"


def _get_profile(s, a):
    u = _me(s)
    return (f"{u['first']} {u['last']}, tier={u['tier']}, gift card CHF {u['gift_card']}, "
            f"addresses={u['addresses']}, payment={u['payment_methods']}")


def _list_orders(s, a):
    lines = []
    for oid in _me(s)["orders"]:
        o = _order(s, oid)
        names = ", ".join(i["name"] for i in o["items"])
        age = (f", delivered {s.db['today'] - o['delivered_day']} days ago"
               if o["delivered_day"] else "")
        lines.append(f"{oid}: {o['status']}{age} -- {names}")
    return "\n".join(lines) or "no orders"


def _get_order_details(s, a):
    o = _order(s, a["order_id"])
    age = (f", delivered {s.db['today'] - o['delivered_day']} days ago"
           if o["delivered_day"] else "")
    return (f"{a['order_id']}: status={o['status']}{age}, "
            f"items={[(i['name'], i.get('size'), i['qty']) for i in o['items']]}, "
            f"modified={o['modified']}")


def _track(s, a):
    return f"order {a['order_id']} is with the carrier, 2 stops away"


def _cancel(s, a):
    _order(s, a["order_id"])["status"] = "cancelled"
    return f"order {a['order_id']} cancelled; refund to original payment method"


def _update_address(s, a):
    _order(s, a["order_id"])["address_id"] = a.get("address_id", "A1")
    return f"shipping address of {a['order_id']} updated to {a.get('address_id', 'A1')}"


def _modify_items(s, a):
    o = _order(s, a["order_id"])
    o["modified"] = True
    o["items"][0]["qty"] = int(a.get("qty", o["items"][0]["qty"]))
    return (f"order {a['order_id']} items updated (qty={o['items'][0]['qty']}); "
            f"the order is now locked against further modification")


def _return_order(s, a):
    o = _order(s, a["order_id"])
    o["status"] = "return_requested"
    o["refund_target"] = a.get("refund_target", "original")
    return f"return requested for {a['order_id']}, refund to {o['refund_target']}"


def _exchange(s, a):
    o = _order(s, a["order_id"])
    o["status"] = "exchange_requested"
    o["items"][0]["size"] = a.get("new_size", o["items"][0]["size"])
    return f"exchange requested for {a['order_id']} -> size {o['items'][0]['size']}"


def _search(s, a):
    q = str(a.get("query", "")).lower()
    hits = [(pid, p) for pid, p in s.db["products"].items()
            if q and q in p["name"].lower() and p["in_stock"]]
    return "\n".join(f"{pid}: {p['name']} CHF {p['price']}"
                     f"{' sizes ' + '/'.join(p['sizes']) if p['sizes'] else ''}"
                     for pid, p in hits[:8]) or "no matching products"


def _product_details(s, a):
    p = s.db["products"].get(a.get("product_id"), None)
    return str(p) if p else "unknown product"


def _add_to_cart(s, a):
    _cart(s).append({"product_id": a["product_id"], "size": a.get("size"),
                     "qty": int(a.get("qty", 1))})
    return f"added {a['product_id']} to cart ({len(_cart(s))} items)"


def _view_cart(s, a):
    return str(_cart(s)) or "cart is empty"


def _clear_cart(s, a):
    s.db["carts"][s.authenticated_user] = []
    return "cart cleared"


def _place_order(s, a):
    wid = f"W{90100 + sum(1 for o in s.db['orders'] if o.startswith('W901')):05d}"
    items = [{"product_id": c["product_id"],
              "name": s.db["products"][c["product_id"]]["name"],
              "qty": c["qty"], "size": c.get("size")} for c in _cart(s)]
    s.db["orders"][wid] = {"user_id": s.authenticated_user, "status": "pending",
                           "items": items, "address_id": a.get("address_id", "A1"),
                           "payment_id": a.get("payment_id", "PM1"),
                           "delivered_day": None, "modified": False}
    _me(s)["orders"].append(wid)
    s.db["carts"][s.authenticated_user] = []
    return f"order {wid} placed ({len(items)} items)"


def _delete_payment(s, a):
    _me(s)["payment_methods"].pop(a.get("payment_id"), None)
    return f"payment method {a.get('payment_id')} deleted"


def _gift_balance(s, a):
    return f"gift card balance: CHF {_me(s)['gift_card']}"


def _write_review(s, a):
    return f"review recorded for order {a['order_id']}"


def _pause_sub(s, a):
    _me(s)["subscriptions"][a["subscription_id"]]["status"] = "paused"
    return f"subscription {a['subscription_id']} paused"


def _resume_sub(s, a):
    _me(s)["subscriptions"][a["subscription_id"]]["status"] = "active"
    return f"subscription {a['subscription_id']} resumed"


def _list_subs(s, a):
    return str(_me(s)["subscriptions"]) or "no subscriptions"


def _escalate(s, a):
    s.scratch["escalated"] = True
    return "escalated to a human support agent; they will follow up by email"


# --------------------------------------------------------------------------- #
# Candidate bindings (enum narrowing): the user's own orders passing each guard.
# --------------------------------------------------------------------------- #
def _own_orders(s: State) -> list[dict]:
    if not _auth(s):
        return []
    return [{"order_id": oid} for oid in _me(s)["orders"]]


def _own_subs(s: State) -> list[dict]:
    if not _auth(s):
        return []
    return [{"subscription_id": sid} for sid in _me(s)["subscriptions"]]


def _own_payments(s: State) -> list[dict]:
    if not _auth(s):
        return []
    return [{"payment_id": pid} for pid in _me(s)["payment_methods"]]


def _instock_products(s: State) -> list[dict]:
    """One candidate per in-stock product: advertisement-time applicability for
    add_to_cart. The domain is large, so tool_spec leaves it free-form (no enum)."""
    if not _auth(s):
        return []
    return [{"product_id": pid} for pid, p in s.db["products"].items()
            if p["in_stock"]]


def _checkout_bindings(s: State) -> list[dict]:
    """Address x payment combinations; empty (-> not advertised, pending signifier)
    while the cart is empty."""
    if not _auth(s) or not _cart(s):
        return []
    return [{"address_id": a, "payment_id": p}
            for a in _me(s)["addresses"] for p in _me(s)["payment_methods"]]


def _refund_targets(s: State) -> list[dict]:
    """Refund target domain per policy: gift card only for gold members."""
    out = []
    for b in _own_orders(s):
        out.append({**b, "refund_target": "original"})
        if _auth(s) and _me(s)["tier"] == "gold":
            out.append({**b, "refund_target": "gift_card"})
    return out


_OID = {"type": "object", "properties": {"order_id": {"type": "string"}},
        "required": ["order_id"]}
_NOARG = {"type": "object", "properties": {}}


def _aff(name, desc, params, guard, effect, rel="act", candidates=None, purposes=None,
         unlock_hint=None):
    kw = {}
    if candidates:
        kw["candidates"] = candidates
    return Affordance(name, desc, params, guard=guard, effect=effect, rel=rel,
                      purposes=purposes or set(), unlock_hint=unlock_hint, **kw)


AFFORDANCES = [
    # -- authentication ------------------------------------------------------ #
    _aff("find_user_by_email", "Authenticate the customer by email address.",
         {"type": "object", "properties": {"email": {"type": "string"}},
          "required": ["email"]},
         lambda s, a: not _auth(s), _find_by_email, rel="authenticate"),
    _aff("find_user_by_name_zip",
         "Authenticate the customer by first name, last name, and zip code.",
         {"type": "object", "properties": {"first": {"type": "string"},
                                           "last": {"type": "string"},
                                           "zip": {"type": "string"}},
          "required": ["first", "last", "zip"]},
         lambda s, a: not _auth(s), _find_by_name_zip, rel="authenticate"),
    # -- profile & payments -------------------------------------------------- #
    _aff("get_profile", "Show the customer's profile, addresses, payment methods, "
         "membership tier, and gift card balance.", _NOARG,
         lambda s, a: _auth(s), _get_profile, rel="inspect"),
    _aff("delete_payment_method", "Delete a stored payment method. Not allowed for the "
         "customer's only remaining payment method.",
         {"type": "object", "properties": {"payment_id": {"type": "string"}},
          "required": ["payment_id"]},
         lambda s, a: _auth(s) and a.get("payment_id") in _me(s)["payment_methods"]
         and len(_me(s)["payment_methods"]) > 1,
         _delete_payment, candidates=_own_payments, purposes={"profile"}),
    _aff("get_gift_card_balance", "Show the customer's gift card balance.", _NOARG,
         lambda s, a: _auth(s), _gift_balance, rel="inspect", purposes={"refund"}),
    # -- catalog & cart ------------------------------------------------------ #
    _aff("search_products", "Search the product catalog by name.",
         {"type": "object", "properties": {"query": {"type": "string"}},
          "required": ["query"]},
         lambda s, a: _auth(s), _search, rel="inspect", purposes={"buy"}),
    _aff("get_product_details", "Show details for one product.",
         {"type": "object", "properties": {"product_id": {"type": "string"}},
          "required": ["product_id"]},
         lambda s, a: _auth(s), _product_details, rel="inspect", purposes={"buy"}),
    _aff("add_to_cart", "Add a product (with optional size and quantity) to the cart.",
         {"type": "object", "properties": {"product_id": {"type": "string"},
                                           "size": {"type": "string"},
                                           "qty": {"type": "integer"}},
          "required": ["product_id"]},
         lambda s, a: _auth(s) and a.get("product_id") in s.db["products"]
         and s.db["products"][a["product_id"]]["in_stock"],
         _add_to_cart, candidates=_instock_products, purposes={"buy"}),
    _aff("view_cart", "Show the current cart.", _NOARG,
         lambda s, a: _auth(s), _view_cart, rel="inspect", purposes={"buy"}),
    _aff("clear_cart", "Empty the cart.", _NOARG,
         lambda s, a: _auth(s) and len(_cart(s)) > 0, _clear_cart, purposes={"buy"}),
    _aff("place_order", "Place an order for the items in the cart, using a stored "
         "address and payment method. The cart must not be empty.",
         {"type": "object", "properties": {"address_id": {"type": "string"},
                                           "payment_id": {"type": "string"}},
          "required": ["address_id", "payment_id"]},
         lambda s, a: _auth(s) and len(_cart(s)) > 0
         and a.get("address_id") in _me(s)["addresses"]
         and a.get("payment_id") in _me(s)["payment_methods"],
         _place_order, candidates=_checkout_bindings, purposes={"buy"},
         unlock_hint="requires a non-empty cart; use add_to_cart first"),
    # -- orders: inspection --------------------------------------------------- #
    _aff("list_orders", "List the customer's orders with status and items.", _NOARG,
         lambda s, a: _auth(s), _list_orders, rel="inspect"),
    _aff("get_order_details", "Show one of the customer's orders in detail.", _OID,
         lambda s, a: _owns(s, a.get("order_id")), _get_order_details, rel="inspect",
         candidates=_own_orders),
    _aff("track_order", "Track a shipped order.", _OID,
         lambda s, a: _owns(s, a.get("order_id"))
         and _order(s, a["order_id"])["status"] == "shipped",
         _track, rel="inspect", candidates=_own_orders, purposes={"track"}),
    # -- orders: lifecycle ----------------------------------------------------- #
    _aff("cancel_order", "Cancel an order. Allowed only while its status is 'pending'.",
         _OID,
         lambda s, a: _owns(s, a.get("order_id"))
         and _order(s, a["order_id"])["status"] == "pending",
         _cancel, candidates=_own_orders, purposes={"cancel"}),
    _aff("update_shipping_address", "Change the shipping address of an order. Allowed "
         "only while the order is 'pending' and not yet modified.",
         {"type": "object", "properties": {"order_id": {"type": "string"},
                                           "address_id": {"type": "string"}},
          "required": ["order_id", "address_id"]},
         lambda s, a: _owns(s, a.get("order_id"))
         and _order(s, a["order_id"])["status"] == "pending"
         and not _order(s, a["order_id"])["modified"],
         _update_address, candidates=_own_orders, purposes={"modify"}),
    _aff("modify_order_items", "Change items/quantities of a pending order. Single-use: "
         "afterwards the order is locked against any further modification.",
         {"type": "object", "properties": {"order_id": {"type": "string"},
                                           "qty": {"type": "integer"}},
          "required": ["order_id"]},
         lambda s, a: _owns(s, a.get("order_id"))
         and _order(s, a["order_id"])["status"] == "pending"
         and not _order(s, a["order_id"])["modified"],
         _modify_items, candidates=_own_orders, purposes={"modify"}),
    _aff("return_order", "Request a return. Allowed only while the order is 'delivered' "
         f"and within {RETURN_WINDOW} days of delivery. Refund goes to the original "
         "payment method; gold members may choose 'gift_card' instead.",
         {"type": "object", "properties": {"order_id": {"type": "string"},
                                           "refund_target": {"type": "string"}},
          "required": ["order_id"]},
         lambda s, a: _owns(s, a.get("order_id")) and _in_return_window(s, a["order_id"])
         and (a.get("refund_target", "original") == "original"
              or _me(s)["tier"] == "gold"),
         _return_order, candidates=_refund_targets, purposes={"return"}),
    _aff("exchange_item", "Exchange an item for another size. Allowed only while the "
         f"order is 'delivered' and within {RETURN_WINDOW} days of delivery.",
         {"type": "object", "properties": {"order_id": {"type": "string"},
                                           "new_size": {"type": "string"}},
          "required": ["order_id", "new_size"]},
         lambda s, a: _owns(s, a.get("order_id")) and _in_return_window(s, a["order_id"]),
         _exchange, candidates=_own_orders, purposes={"exchange"}),
    # -- reviews & subscriptions ---------------------------------------------- #
    _aff("write_review", "Write a product review for a delivered order.",
         {"type": "object", "properties": {"order_id": {"type": "string"},
                                           "text": {"type": "string"}},
          "required": ["order_id", "text"]},
         lambda s, a: _owns(s, a.get("order_id"))
         and _order(s, a["order_id"])["status"] == "delivered",
         _write_review, candidates=_own_orders, purposes={"review"}),
    _aff("list_subscriptions", "List the customer's subscriptions.", _NOARG,
         lambda s, a: _auth(s), _list_subs, rel="inspect", purposes={"subscription"}),
    _aff("pause_subscription", "Pause a subscription. Allowed only while it is active.",
         {"type": "object", "properties": {"subscription_id": {"type": "string"}},
          "required": ["subscription_id"]},
         lambda s, a: _auth(s)
         and _me(s)["subscriptions"].get(a.get("subscription_id"), {}).get("status")
         == "active",
         _pause_sub, candidates=_own_subs, purposes={"subscription"}),
    _aff("resume_subscription", "Resume a subscription. Allowed only while it is paused.",
         {"type": "object", "properties": {"subscription_id": {"type": "string"}},
          "required": ["subscription_id"]},
         lambda s, a: _auth(s)
         and _me(s)["subscriptions"].get(a.get("subscription_id"), {}).get("status")
         == "paused",
         _resume_sub, candidates=_own_subs, purposes={"subscription"}),
    # -- support ---------------------------------------------------------------- #
    _aff("escalate_to_agent", "Hand the conversation to a human support agent (always "
         "allowed; use when a request cannot be fulfilled within policy).", _NOARG,
         lambda s, a: _auth(s), _escalate),
]

POLICY = (
    "Customer-service policy (binding). 1) Authenticate the customer first, by email or "
    "by name + zip; never act on an unauthenticated session. 2) Only ever act on the "
    "authenticated customer's own orders, subscriptions, and payment methods. 3) An "
    "order can be cancelled only while its status is 'pending'. 4) The shipping address "
    "and the items of an order can be changed only while it is 'pending'; changing the "
    "items is single-use and locks the order against ANY further modification, "
    "including address changes -- if both are requested, change the address first. "
    f"5) Returns and exchanges are allowed only while an order is 'delivered' and at "
    f"most {RETURN_WINDOW} days after delivery; outside the window, do not attempt them "
    "and offer to escalate instead. 6) Refunds go to the original payment method; only "
    "gold-tier members may choose a gift-card refund. 7) Reviews only for delivered "
    "orders. 8) A subscription can be paused only while active and resumed only while "
    "paused. 9) A customer's only remaining payment method must never be deleted. "
    "10) Orders can be placed only from a non-empty cart with a stored address and "
    "payment method. 11) If a request cannot be fulfilled within this policy, do not "
    "attempt it; explain and escalate to a human agent when appropriate."
)


def _init() -> State:
    return State(db=_seed_db(),
                 scratch={"creds": {"email": "emma.berger@mail.com"}})


def _st(s, oid):
    return s.db["orders"][oid]["status"]


TASKS = [
    # Multi-action across two orders, referenced by content, not id.
    Task("cancel_and_return",
         "Hi, I'm Emma Berger (emma.berger@mail.com). Please cancel my order with the "
         "espresso machine, and start a return for the headphones order that arrived "
         "last week.",
         init=_init,
         goal=lambda s: _st(s, "W90001") == "cancelled"
         and _st(s, "W90002") == "return_requested"
         and _st(s, "W90003") == "delivered",
         scripted_intent=[("cancel_order", {"order_id": "W90001"}),
                          ("return_order", {"order_id": "W90002"})],
         agent_ctx=AgentContext(goal={"cancel", "return"})),
    # Return-window trap: delivered 45 days ago; correct outcome = NOT returned.
    Task("return_window_trap",
         "I'm Emma Berger (emma.berger@mail.com). I want to return my running shoes "
         "order, it doesn't fit.",
         init=_init,
         goal=lambda s: _st(s, "W90003") == "delivered",
         scripted_intent=[("return_order", {"order_id": "W90003"})],
         agent_ctx=AgentContext(goal={"return"})),
    # Ordering task: modify locks the order, so the address must be changed FIRST.
    Task("address_then_modify",
         "Emma Berger, emma.berger@mail.com. For my pending cookbook order: change the "
         "shipping address to my office (A2), and also bump the quantity to 2.",
         init=_init,
         goal=lambda s: s.db["orders"]["W90006"]["address_id"] == "A2"
         and s.db["orders"]["W90006"]["items"][0]["qty"] == 2,
         scripted_intent=[("update_shipping_address",
                           {"order_id": "W90006", "address_id": "A2"}),
                          ("modify_order_items", {"order_id": "W90006", "qty": 2})],
         agent_ctx=AgentContext(goal={"modify"})),
    # Gift-card refund trap: Emma is basic tier -> refund must go to 'original'.
    Task("giftcard_refund_trap",
         "Emma Berger (emma.berger@mail.com) again. Return the black t-shirt order and "
         "put the money on my gift card please.",
         init=_init,
         goal=lambda s: _st(s, "W90004") == "return_requested"
         and s.db["orders"]["W90004"].get("refund_target") == "original",
         scripted_intent=[("return_order",
                           {"order_id": "W90004", "refund_target": "original"})],
         agent_ctx=AgentContext(goal={"return", "refund"})),
    # Exchange within window.
    Task("exchange_size",
         "I'm Emma Berger, emma.berger@mail.com. The t-shirt I got a few days ago is "
         "too small -- exchange it for size L.",
         init=_init,
         goal=lambda s: _st(s, "W90004") == "exchange_requested"
         and s.db["orders"]["W90004"]["items"][0]["size"] == "L",
         scripted_intent=[("exchange_item", {"order_id": "W90004", "new_size": "L"})],
         agent_ctx=AgentContext(goal={"exchange"})),
    # Cross-user trap: the id belongs to someone else; correct outcome = untouched.
    Task("cross_user_trap",
         "Emma Berger, emma.berger@mail.com. Please cancel order W00003, I think "
         "that's mine.",
         init=_init,
         goal=lambda s: _st(s, "W00003") != "cancelled",
         scripted_intent=[("cancel_order", {"order_id": "W00003"})],
         agent_ctx=AgentContext(goal={"cancel"})),
    # Subscription already paused: correct outcome = still paused, no illegal call.
    Task("pause_paused_sub",
         "It's Emma (emma.berger@mail.com). Pause my coffee subscription for now.",
         init=_init,
         goal=lambda s: s.db["users"]["U0001"]["subscriptions"]["S1"]["status"]
         == "paused",
         scripted_intent=[("pause_subscription", {"subscription_id": "S1"})],
         agent_ctx=AgentContext(goal={"subscription"})),
    # Only-payment-method trap: correct outcome = not deleted.
    Task("delete_only_payment_trap",
         "Emma Berger, emma.berger@mail.com. Remove my Mastercard from my account.",
         init=_init,
         goal=lambda s: len(s.db["users"]["U0001"]["payment_methods"]) == 1,
         scripted_intent=[("delete_payment_method", {"payment_id": "PM1"})],
         agent_ctx=AgentContext(goal={"profile"})),
    # Purchase flow: search -> cart -> checkout.
    Task("buy_hoodie",
         "Hi, Emma Berger here (emma.berger@mail.com). Order me the Pro Black Hoodie "
         "in size L, to my home address, paid with my stored card.",
         init=_init,
         goal=lambda s: any(o["user_id"] == "U0001" and o["status"] == "pending"
                            and any(i["product_id"] == "P9001" and i.get("size") == "L"
                                    for i in o["items"])
                            for o in s.db["orders"].values()),
         scripted_intent=[("add_to_cart", {"product_id": "P9001", "size": "L"}),
                          ("place_order", {"address_id": "A1", "payment_id": "PM1"})],
         agent_ctx=AgentContext(goal={"buy"})),
    # Simple control task.
    Task("track_lamp",
         "Emma Berger, emma.berger@mail.com -- where is my desk lamp order?",
         init=_init,
         goal=lambda s: True,     # success = no illegal call; tracked via metrics
         scripted_intent=[("track_order", {"order_id": "W90005"})],
         agent_ctx=AgentContext(goal={"track"})),
]

ENV = Env(name="shop", affordances=AFFORDANCES, tasks=TASKS, policy=POLICY,
          persona="You are a customer-service agent for an online shop.")
