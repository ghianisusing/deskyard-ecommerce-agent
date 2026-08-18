# Customer service agent — e-commerce starter

A small working store (products, cart, checkout, accounts) with an AI
support agent that floats on every page. The agent answers general
questions from a knowledge base, sees the live product catalog, and — if
the customer is logged in — sees their own real order history, so it can
answer things like "where's my order" without you writing any lookup code
by hand.

## Setup

1. Get an API key at https://platform.openai.com/api-keys (this is
   separate from a ChatGPT subscription — it's billed by usage, and
   OpenAI no longer offers an ongoing free tier, so you'll need to add
   billing details before it works).

2. Create a virtual environment and install dependencies:
   ```
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Add your API key:
   ```
   cp .env.example .env
   # then edit .env and paste in your OPENAI_API_KEY
   ```

   Optional: to receive real notifications when the agent escalates a
   chat, also set `SUPPORT_NOTIFICATION_EMAIL` and/or
   `SLACK_ESCALATION_WEBHOOK_URL` in `.env`. Leave them blank and
   escalation emails just print to your terminal (Django's console email
   backend) — fine for local dev.

4. Run migrations (creates the database tables, plus a starter product
   catalog and knowledge base):
   ```
   python manage.py migrate
   ```

5. Create an admin login so you can manage products and knowledge base
   entries:
   ```
   python manage.py createsuperuser
   ```

6. Start the server:
   ```
   python manage.py runserver
   ```

7. Open http://127.0.0.1:8000/ to browse the shop. Sign up for a
   customer account (or log in), add something to your cart, and check
   out — that creates a real order. Then open the chat bubble in the
   bottom-right corner and ask "where's my order?" — the agent will
   answer from your actual order.

   Visit http://127.0.0.1:8000/admin/ to add/edit products, knowledge
   base entries, or view all orders.

## How it works

- `store/models.py` — `Product`, `Order`, `OrderItem`. A real shopping
  flow: browse -> cart (session-based) -> checkout -> `Order` row created
  for the logged-in customer, stock decremented.
- `agent/models.py` — `KnowledgeBaseEntry`, the general policy facts
  (shipping, returns, payment) the agent can answer from. Manage these
  at `/admin/` too.
- `agent/views.py` — `chat_api` builds the system prompt fresh on every
  message from three sources: the knowledge base, the live product
  catalog, and (if logged in) the customer's own recent orders. It's
  told explicitly never to invent an order number or status that isn't
  in that context.
- `agent/templates/agent/chat_widget.html` + `chat.js` / `chat.css` — the
  floating chat bubble, included on every store page via `store/base.html`.
- Escalation: if the agent can't resolve something (or the customer asks
  for a human), it tags the reply, the widget shows a flag, and
  `agent/signals.py` fires a real notification (email and/or Slack) to
  whoever's configured to receive them — see "Escalation notifications"
  below.
- **Deskie** — the agent has a small hand-drawn SVG mascot
  (`agent/templates/agent/face.html`) with CSS-animated expressions
  (idle, listening, thinking, happy, concerned, speaking) driven by a
  `data-state` attribute that `chat.js` toggles at each point in the
  conversation. Each agent reply in the transcript gets its own frozen
  snapshot avatar (cloned from the live one, not duplicated markup).
- **Voice call mode** — click "📞 Call" in the widget header to talk to
  Deskie instead of typing.
  - **Your voice → text**: the browser's built-in Web Speech API
    (`SpeechRecognition`) — no external service, no cost.
  - **Deskie's voice**: OpenAI's TTS API (`agent/views.py:tts_api`), a
    real neural voice ("nova" by default — natural and friendly-sounding,
    not the robotic default browser voice), reusing the same
    `OPENAI_API_KEY` the chat agent already uses. If that request fails
    for any reason (quota, network, missing key), the frontend
    automatically falls back to the browser's own `SpeechSynthesis`
    rather than going silent.
  - **Animation sync**: while Deskie speaks, her mouth movement is driven
    by the *actual* audio waveform in real time via the Web Audio API's
    `AnalyserNode` — genuine amplitude-based sync, not a fixed-timing
    loop. Falls back to a CSS keyframe loop if Web Audio setup fails.
  - **Floating assistant**: during an active call, Deskie moves out of
    the chat panel into a separate floating element
    (`#deskie-floating`) — the panel and its small toggle button hide
    themselves, and this bigger assistant (with its own status text and
    "End Call" button) becomes the visible UI. A "💬 View chat" button
    lets you peek at the text transcript mid-call without hanging up.
  - Both the mic input and Deskie's replies go through the exact same
    `/api/chat/` endpoint as typed messages, so escalation and the
    knowledge base behave identically either way.
  - **Browser support varies** for the mic side: solid in Chrome/Edge,
    weak-to-absent in Firefox/Safari — the call button disables itself
    with an explanatory tooltip when unsupported, rather than failing
    silently.
  - This is a browser-side voice *chat*, not a real phone call —
    "transfer to a human" still means the existing email/Slack
    escalation notification, not a live person joining the call. A real
    phone number would need a telephony provider (e.g. Twilio) and a
    paid account, which is a separate, much larger integration.
  - **Cost note**: `/api/tts/` shares the same per-user rate limiter as
    `/api/chat/` (`CHAT_RATE_LIMIT_MAX`/`WINDOW`), since every voice
    turn calls both once — this halves the effective number of
    conversational turns available in the rate-limit window compared to
    text chat, which is intentional (otherwise TTS could be hit directly
    at unbounded per-character API cost with nothing gating it).

## Design

The storefront ("Deskyard") has a "technical spec sheet" identity built
around what it actually sells — desk/WFH gear: a blueprint-grid
background, corner registration marks on product cards (revealed on
hover), and monospace price tags/SKUs. Type is Big Shoulders (display) +
IBM Plex Sans (body) + IBM Plex Mono (prices, specs) — loaded from Google
Fonts, so an internet connection is needed for the fonts to render as
designed (falls back to system sans-serif otherwise). The catalog now has
10 products across two seed migrations, each tagged with a category.

Every product card shows a hand-drawn SVG wireframe icon by default. Upload
a real photo for a product at `/admin/` and the storefront automatically
swaps to a full-bleed photo on the shop grid, product page, and cart —
no template changes needed either way.

## Shop features

- **Search** — filters by product name or description (`/?q=...`).
- **Category filter** — Input Devices, Ergonomics, Audio & Video,
  Lighting, Cable Management, Accessories, Other. Filters combine with
  search.
- **Pagination** — 9 products per page; filters carry across pages.
- **Product images** — optional per-product upload via `/admin/`
  (`Product.image`). Falls back to the wireframe icon when unset. Stored
  under `media/` locally (gitignored) — served by Django only in
  `DEBUG` mode; swap for real object storage (S3, etc.) before deploying.

## Recent hardening

- **Rate limiting** — `/api/chat/` caps messages per session/IP (defaults:
  10 messages / 60s, tunable via `CHAT_RATE_LIMIT_MAX` /
  `CHAT_RATE_LIMIT_WINDOW` in `.env`). Uses Django's in-memory cache —
  fine for one dev server; swap for Redis before running multiple worker
  processes, since in-memory cache isn't shared across processes.
- **Secret key** — no longer hardcoded. Set `DJANGO_SECRET_KEY` in `.env`
  for anything beyond your laptop; locally it falls back to a random key
  generated once into `.dev_secret_key` (gitignored).
- **Checkout integrity** — wrapped in a database transaction and now
  validates stock for every cart line *before* creating any order rows,
  so a checkout that would oversell a product is rejected cleanly
  instead of leaving a partial order or negative-adjacent stock.
- **Checkout race condition** — stock validation locks each product row
  with `select_for_update()` (rows locked in a consistent pk order to
  avoid deadlocks between overlapping carts), so two customers can't both
  pass the stock check on the last unit at the same instant. A DB-level
  `CheckConstraint` also guarantees `stock` can never go negative
  regardless of what the application code does. Note: `select_for_update()`
  is a no-op on SQLite — this only takes real effect once you're on
  Postgres or MySQL.
- **Escalation notifications** — when the agent flags a chat with
  `[ESCALATE]`, `agent/signals.py` fires a real email and/or Slack
  message the moment the `ChatLog` row is written, instead of that flag
  only existing as a boolean nobody's watching in `/admin/`. Both are
  optional and off by default — set `SUPPORT_NOTIFICATION_EMAIL` and/or
  `SLACK_ESCALATION_WEBHOOK_URL` in `.env` to enable. Either channel
  failing (bad SMTP config, dead webhook) is caught and logged — it can
  never break the chat response the customer already received.
- **Cost control** — conversation history sent to OpenAI is capped to the
  last `CHAT_HISTORY_MAX_TURNS` turns (default 10) instead of growing
  unbounded as a chat gets longer.
- **Logging** — every `/api/chat/` call (success, escalation, or error) is
  recorded in a `ChatLog` row, visible read-only at `/admin/` under
  Agent > Chat logs.

## Running tests

```
python manage.py test
```

Covers: checkout stock validation (rejects overselling, doesn't
partially apply on failure), a concurrency test proving two simultaneous
checkouts can't both claim the last unit of stock, order total
calculation, escalation tag parsing, escalation email/Slack notifications
actually firing (and failing silently if misconfigured), chat rate
limiting, product search/category filtering/pagination, product image
rendering (falls back to the SVG icon when unset, renders the real image
when uploaded), Deskie/voice-call/floating-assistant markup rendering,
and the TTS endpoint (success, error handling, text length capping, and
that its rate limit is genuinely shared with the chat endpoint).

## Next steps

- Swap SQLite for Postgres or MySQL in `csa_project/settings.py`'s
  `DATABASES` setting when you're ready to deploy — the models and
  migrations don't need to change. This also activates the
  `select_for_update()` checkout locking, which is currently a no-op on
  SQLite.
- Add real payment processing at checkout (currently it just creates the
  order — no payment is actually taken).
- Escalations notify a human now, but there's still no ticket/queue to
  work from — just an inbox or Slack channel. A `claimed_by` /
  `resolved_at` field (or a small dedicated `EscalationTicket` model)
  plus a scoped `is_staff`-but-not-superuser support role would turn
  "someone got an email" into an actual workable queue.
- Let the agent look up an order by number for guests who aren't logged
  in (with some form of identity check, e.g. matching an email).
- Replace the context-stuffing prompt in `agent/views.py` (which sends
  the *entire* catalog, knowledge base, and order history on every
  message) with OpenAI function calling / tool use, so the agent fetches
  only what a given question actually needs. This matters more as the
  catalog and knowledge base grow past demo size.
