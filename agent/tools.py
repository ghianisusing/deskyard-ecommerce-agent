"""Tools the chat agent can call to fetch store data on demand.

Instead of pasting the whole catalog, knowledge base and order history into
every prompt, the model gets these tools and asks only for what a question
needs. Each tool returns JSON text for the model to read.

Order tools only ever look at the logged-in customer's own orders, and are
not offered to guests at all.
"""

import json
import logging
import re
from collections.abc import Callable

from django.db.models import Q

from store.models import Product

from .models import KnowledgeBaseEntry

logger = logging.getLogger(__name__)

MAX_PRODUCT_RESULTS = 10
MAX_ORDER_RESULTS = 5
# Words too common to be useful as product search terms.
STOP_WORDS = {"the", "and", "for", "with", "you", "your", "have", "any", "what", "how", "much", "does"}


def _product_dict(product: Product) -> dict:
    return {
        "name": product.name,
        "price": f"${product.price}",
        "in_stock": product.stock > 0,
        "category": product.get_category_display() if product.category else "",
        "description": product.description,
    }


def search_products(user, query: str = "", category: str = "") -> dict:
    """Products whose name, description or category match any word of the
    query, best matches first. An empty query lists the catalog (capped)."""
    products = Product.objects.all()
    if category:
        products = products.filter(category=category)

    tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
    words = [w for w in tokens if len(w) >= 3 and w not in STOP_WORDS]
    if words:
        match = Q()
        for word in words:
            match |= Q(name__icontains=word) | Q(description__icontains=word) | Q(category__icontains=word)
        products = products.filter(match)

    def score(product: Product) -> int:
        text = f"{product.name} {product.description} {product.category}".lower()
        return sum(word in product.name.lower() for word in words) * 2 + sum(word in text for word in words)

    ranked = sorted(products, key=lambda p: (-score(p), p.name))
    results = [_product_dict(p) for p in ranked[:MAX_PRODUCT_RESULTS]]
    return {"products": results, "more_results": len(ranked) > MAX_PRODUCT_RESULTS}


def get_policies(user, topics: list | None = None) -> dict:
    """Knowledge base entries for the requested topics (case-insensitive).
    Unknown topics are reported back with the list of real ones."""
    entries = list(KnowledgeBaseEntry.objects.all())
    by_topic = {entry.topic.lower(): entry for entry in entries}
    wanted = [t for t in (topics or []) if isinstance(t, str)]

    found, unknown = [], []
    for topic in wanted:
        entry = by_topic.get(topic.strip().lower())
        if entry:
            found.append({"topic": entry.topic, "content": entry.content})
        else:
            unknown.append(topic)

    result = {"entries": found}
    if unknown or not wanted:
        result["unknown_topics"] = unknown
        result["available_topics"] = [entry.topic for entry in entries]
    return result


def _order_dict(order) -> dict:
    return {
        "order_number": order.id,
        "status": order.get_status_display(),
        "placed": f"{order.created_at:%b %d, %Y}",
        "items": [f"{item.quantity}x {item.product.name}" for item in order.items.all()],
        "total": f"${order.total}",
        "payment": order.get_payment_status_display(),
        # Empty for orders placed before addresses were collected.
        "ships_to": ", ".join(order.shipping_address_lines()) or "no address on file",
    }


def get_my_orders(user) -> dict:
    """The customer's most recent orders, newest first."""
    # Prefetch items and their products: two extra queries total, not two per order.
    orders = user.orders.prefetch_related("items__product").order_by("-created_at")[:MAX_ORDER_RESULTS]
    return {"orders": [_order_dict(order) for order in orders]}


def get_order(user, order_number=None) -> dict:
    """One of the customer's own orders by number. Someone else's order looks
    exactly like a missing one, so order numbers can't be probed."""
    try:
        order_id = int(str(order_number).lstrip("#"))
    except (TypeError, ValueError):
        return {"error": "That isn't a valid order number."}
    order = user.orders.prefetch_related("items__product").filter(pk=order_id).first()
    if order is None:
        return {"error": f"No order #{order_id} found on this customer's account."}
    return {"order": _order_dict(order)}


def _schema(name: str, description: str, properties: dict, required: list | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


SEARCH_PRODUCTS = _schema(
    "search_products",
    "Look up products in the store catalog: price, whether it's in stock, category and "
    "description. Use for any question about a product, price or availability.",
    {
        "query": {
            "type": "string",
            "description": "Words to match against product names and descriptions, e.g. 'desk lamp'. "
            "Leave empty to browse.",
        },
        "category": {
            "type": "string",
            "enum": [code for code, _ in Product.CATEGORY_CHOICES],
            "description": "Only return products in this category.",
        },
    },
)

GET_POLICIES = _schema(
    "get_policies",
    "Read store policy entries from the knowledge base (shipping, returns, payment and so on) by topic name.",
    {
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Topic names from the list in the instructions.",
        }
    },
    required=["topics"],
)

GET_MY_ORDERS = _schema(
    "get_my_orders",
    "List the logged-in customer's most recent orders with status, items, total, "
    "payment status and shipping address.",
    {},
)

GET_ORDER = _schema(
    "get_order",
    "Look up one of the logged-in customer's orders by its order number.",
    {"order_number": {"type": "integer", "description": "The order number, without '#'."}},
    required=["order_number"],
)

HANDLERS: dict[str, Callable[..., dict]] = {
    "search_products": search_products,
    "get_policies": get_policies,
    "get_my_orders": get_my_orders,
    "get_order": get_order,
}

SCHEMAS = {
    schema["function"]["name"]: schema for schema in (SEARCH_PRODUCTS, GET_POLICIES, GET_MY_ORDERS, GET_ORDER)
}

# Python types accepted for each JSON schema type, and how to name the type
# in an error. An integer may also arrive as text ("12" or "#12"); get_order
# parses that itself.
_ACCEPTED_TYPES = {"string": (str,), "integer": (int, str), "array": (list,)}
_TYPE_NAMES = {"string": "a string", "integer": "an integer", "array": "a list"}


def _argument_error(name: str, arguments: dict) -> str | None:
    """Why these arguments don't fit the tool's schema, or None if they do.

    The model usually follows the schema but nothing guarantees it, and a
    handler given a list where it expects text would otherwise crash.
    """
    properties = SCHEMAS[name]["function"]["parameters"]["properties"]
    for key, value in arguments.items():
        spec = properties.get(key)
        if spec is None:
            return f"unknown argument '{key}'"
        # bool is a subclass of int, so it needs ruling out by name.
        if isinstance(value, bool) or not isinstance(value, _ACCEPTED_TYPES[spec["type"]]):
            return f"'{key}' must be {_TYPE_NAMES[spec['type']]}"
        if "enum" in spec and value not in spec["enum"]:
            return f"'{key}' must be one of: {', '.join(spec['enum'])}"
    return None


def tools_for(user) -> list[dict]:
    """Tool definitions to offer for this customer. Guests get no order tools."""
    tools = [SEARCH_PRODUCTS, GET_POLICIES]
    if user.is_authenticated:
        tools += [GET_MY_ORDERS, GET_ORDER]
    return tools


def run_tool(user, name: str, raw_arguments: str) -> str:
    """Run one tool call from the model and return its result as JSON text.

    Bad input from the model (unknown tool, invalid JSON, wrong arguments)
    comes back as an error message it can read, rather than failing the chat.
    So does a tool that breaks while running, which is also logged: the
    model can then say it couldn't look that up instead of the reply dying.
    """
    offered = {tool["function"]["name"] for tool in tools_for(user)}
    if name not in offered:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "Arguments were not valid JSON."})
    if not isinstance(arguments, dict):
        return json.dumps({"error": "Arguments must be a JSON object."})

    # An optional argument sent as null or "" means the same as leaving it out.
    arguments = {key: value for key, value in arguments.items() if value is not None and value != ""}
    problem = _argument_error(name, arguments)
    if problem:
        return json.dumps({"error": f"Wrong arguments for {name}: {problem}."})
    try:
        result = HANDLERS[name](user, **arguments)
    except Exception:  # noqa: BLE001 - a broken tool must not break the chat
        logger.exception("Tool %s failed with arguments %s", name, raw_arguments)
        return json.dumps({"error": f"{name} isn't working right now."})
    return json.dumps(result)
