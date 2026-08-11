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
  for a human), it tags the reply and the widget shows a flag. That's
  still just a UI flag for now — see next steps.

## Design

The storefront ("Deskyard") has a "technical spec sheet" identity built
around what it actually sells — desk/WFH gear: a blueprint-grid
background, corner registration marks on product cards (revealed on
hover), and monospace price tags/SKUs. Type is Big Shoulders (display) +
IBM Plex Sans (body) + IBM Plex Mono (prices, specs) — loaded from Google
Fonts, so an internet connection is needed for the fonts to render as
designed (falls back to system sans-serif otherwise). The catalog now has
10 products across two seed migrations.

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
partially apply on failure), order total calculation, escalation tag
parsing, and chat rate limiting.

## Next steps

- Swap SQLite for Postgres or MySQL in `csa_project/settings.py`'s
  `DATABASES` setting when you're ready to deploy — the models and
  migrations don't need to change.
- Add real payment processing at checkout (currently it just creates the
  order — no payment is actually taken).
- Build a real escalation path (Slack notification, support ticket) for
  the `[ESCALATE]` flag instead of just showing it in the widget.
- Let the agent look up an order by number for guests who aren't logged
  in (with some form of identity check, e.g. matching an email).
