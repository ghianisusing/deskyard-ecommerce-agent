import json
import os

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI

from store.models import Product

from .knowledge_base import format_knowledge_base
from .models import ChatLog

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
MAX_TTS_CHARS = 2000


def build_product_context() -> str:
    """Live product catalog, so the agent can answer stock/price questions."""
    products = Product.objects.all()
    if not products:
        return ""
    lines = ["Current product catalog:"]
    for product in products:
        stock_note = "in stock" if product.stock > 0 else "out of stock"
        lines.append(f"- {product.name}: ${product.price} ({stock_note})")
    return "\n".join(lines)


def build_order_context(user) -> str:
    """The logged-in customer's own recent orders, so the agent can answer
    'where's my order' without the customer typing an order number."""
    if not user.is_authenticated:
        return (
            "This customer is not logged in, so you don't have their order "
            "history. If they ask about a specific order, ask them to log "
            "in first."
        )
    orders = user.orders.all().order_by("-created_at")[:5]
    if not orders:
        return "This customer is logged in but has no past orders."
    lines = ["This customer's recent orders:"]
    for order in orders:
        items = ", ".join(f"{item.quantity}x {item.product.name}" for item in order.items.all())
        lines.append(
            f"- Order #{order.id}: {order.get_status_display()}, placed "
            f"{order.created_at:%b %d, %Y} — {items} (total ${order.total()})"
        )
    return "\n".join(lines)


def build_system_prompt(request) -> str:
    """Built per-request so knowledge base edits and fresh order/stock data
    are always current, with no server restart needed."""
    sections = [format_knowledge_base(), build_product_context(), build_order_context(request.user)]
    context = "\n\n".join(section for section in sections if section)

    return f"""You are a friendly, concise customer service agent for an
online store. Answer using ONLY the knowledge base and store data below —
if the answer isn't in it, say you're not sure and offer to escalate to a
human. Never invent an order number, status, or product detail that isn't
shown below.

If the customer is upset, asks for something the knowledge base says to
escalate, or explicitly asks for a human, respond with a short apology and
end your reply with exactly this tag on its own line: [ESCALATE]

{context}
"""


def parse_agent_reply(raw_text: str) -> tuple[str, bool]:
    """Split the raw LLM output into (clean_reply_text, should_escalate)."""
    raw_text = (raw_text or "").strip()
    escalate = "[ESCALATE]" in raw_text
    clean_text = raw_text.replace("[ESCALATE]", "").strip()
    return clean_text, escalate


def _rate_limit_key(request) -> str:
    """Rate limit per logged-in user, or per IP for guests."""
    if request.user.is_authenticated:
        return f"chat_rl:user:{request.user.id}"
    ip = request.META.get("REMOTE_ADDR", "unknown")
    return f"chat_rl:ip:{ip}"


def _is_rate_limited(request) -> bool:
    """Sliding-window-ish counter: N messages per WINDOW seconds. Uses the
    default cache (in-memory, per-process) — fine for a single dev server;
    swap for a shared cache like Redis before running multiple workers.
    """
    key = _rate_limit_key(request)
    count = cache.get(key)
    if count is None:
        cache.set(key, 1, timeout=settings.CHAT_RATE_LIMIT_WINDOW)
        return False
    if count >= settings.CHAT_RATE_LIMIT_MAX:
        return True
    try:
        cache.incr(key)
    except ValueError:
        # Key expired between get() and incr() — start a fresh window.
        cache.set(key, 1, timeout=settings.CHAT_RATE_LIMIT_WINDOW)
    return False


def _log_chat(request, message: str, reply: str = "", escalated: bool = False, error: str = ""):
    ChatLog.objects.create(
        user=request.user if request.user.is_authenticated else None,
        message=message,
        reply=reply,
        escalated=escalated,
        error=error,
    )


@csrf_exempt
def chat_api(request):
    """Take a user message + history, return the agent's reply."""
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    if _is_rate_limited(request):
        return JsonResponse(
            {
                "error": (
                    f"You're sending messages too quickly. Please wait a "
                    f"moment and try again (limit: {settings.CHAT_RATE_LIMIT_MAX} "
                    f"messages per {settings.CHAT_RATE_LIMIT_WINDOW}s)."
                )
            },
            status=429,
        )

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    user_message = (body.get("message") or "").strip()
    history = body.get("history") or []  # [{role: "user"|"assistant", content}]

    if not user_message:
        return JsonResponse({"error": "Empty message"}, status=400)

    if not settings.OPENAI_API_KEY:
        return JsonResponse(
            {"error": "Server is missing OPENAI_API_KEY. See README."},
            status=500,
        )

    # Cap how much history gets resent each turn so token cost doesn't grow
    # unbounded as a conversation gets longer.
    max_entries = settings.CHAT_HISTORY_MAX_TURNS * 2
    history = history[-max_entries:]

    messages = [{"role": "system", "content": build_system_prompt(request)}]
    for turn in history:
        role = turn.get("role") if turn.get("role") in ("user", "assistant") else "user"
        messages.append({"role": role, "content": turn.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=500,
        )
    except Exception as exc:  # noqa: BLE001 - surface any provider error to the UI, never crash
        _log_chat(request, user_message, error=str(exc))
        return JsonResponse({"error": f"Agent error: {exc}"}, status=502)

    reply_text = response.choices[0].message.content
    reply_text, escalate = parse_agent_reply(reply_text)

    _log_chat(request, user_message, reply=reply_text, escalated=escalate)

    return JsonResponse({"reply": reply_text, "escalate": escalate})


@csrf_exempt
def tts_api(request):
    """Text -> natural-sounding speech (MP3 bytes) via OpenAI's TTS API,
    used by the browser voice call feature for Deskie's spoken replies.

    Reuses the same rate limiter as chat_api. Since every voice-call turn
    calls this once per chat_api call, that halves the effective number of
    conversational turns available within the rate-limit window compared
    to text chat — an intentional tradeoff: without sharing the limiter, a
    client could hit this endpoint directly in a loop with arbitrary text
    at real per-character API cost, with nothing else gating it.

    If this fails for any reason (missing key, quota, network), the
    frontend falls back to the browser's own built-in speech synthesis —
    a voice call should never go silent just because this endpoint had a
    bad moment.
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)

    if _is_rate_limited(request):
        return JsonResponse({"error": "Too many requests."}, status=429)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    text = (body.get("text") or "").strip()
    if not text:
        return JsonResponse({"error": "Empty text"}, status=400)
    # Defense in depth: normal callers only ever send a chat reply, which
    # is already bounded by chat_api's max_tokens, but this endpoint could
    # in principle be called directly with arbitrary input.
    text = text[:MAX_TTS_CHARS]

    if not settings.OPENAI_API_KEY:
        return JsonResponse({"error": "Server is missing OPENAI_API_KEY."}, status=500)

    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        speech = client.audio.speech.create(
            model=settings.OPENAI_TTS_MODEL,
            voice=settings.OPENAI_TTS_VOICE,
            input=text,
        )
    except Exception as exc:  # noqa: BLE001 - never crash; frontend falls back to browser TTS
        return JsonResponse({"error": f"TTS error: {exc}"}, status=502)

    return HttpResponse(speech.content, content_type="audio/mpeg")
