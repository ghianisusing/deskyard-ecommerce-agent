"""Send the scripted conversations in agent/evals.py to the real model and
report which ones pass.

This calls OpenAI for real (it costs a little and answers vary between
runs), so it isn't part of the test suite or CI. Everything runs in a
throwaway test database; your data and chat logs aren't touched, and
escalation alerts are switched off for the run.
"""

import sys

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.test.runner import DiscoverRunner
from django.urls import reverse

from agent.evals import EVAL_ORDER, EVAL_PRODUCTS, SCENARIOS, Reply, run_checks
from agent.models import ChatLog
from agent.views import MODEL
from store.models import Order, OrderItem, Product


class Command(BaseCommand):
    help = "Run the scripted chat conversations against the real model and report pass/fail."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario",
            action="append",
            dest="scenarios",
            metavar="NAME",
            help="Run only this scenario (repeatable).",
        )
        parser.add_argument("--list", action="store_true", help="List scenario names and exit.")
        parser.add_argument(
            "--show-replies", action="store_true", help="Print every reply, not only failing ones."
        )

    def handle(self, *args, **options):
        # Replies can contain characters a Windows console can't print.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(errors="replace")

        if options["list"]:
            for scenario in SCENARIOS:
                self.stdout.write(scenario.name)
            return

        scenarios = SCENARIOS
        if options["scenarios"]:
            wanted = set(options["scenarios"])
            unknown = wanted - {s.name for s in SCENARIOS}
            if unknown:
                raise CommandError(f"Unknown scenario(s): {', '.join(sorted(unknown))}. Use --list.")
            scenarios = [s for s in SCENARIOS if s.name in wanted]

        if not settings.OPENAI_API_KEY:
            raise CommandError("OPENAI_API_KEY is not set. These evals call the real model.")

        runner = DiscoverRunner(verbosity=0, interactive=False)
        runner.setup_test_environment()
        old_config = runner.setup_databases()
        try:
            with override_settings(
                SLACK_ESCALATION_WEBHOOK_URL="",
                SUPPORT_NOTIFICATION_EMAIL="",
                CHAT_RATE_LIMIT_MAX=10_000,
            ):
                failed = self._run(scenarios, options["show_replies"])
        finally:
            runner.teardown_databases(old_config)
            runner.teardown_test_environment()

        if failed:
            raise CommandError(f"{failed} of {len(scenarios)} scenario(s) failed.")

    def _run(self, scenarios, show_replies: bool) -> int:
        users, context = _create_eval_data()
        failed = 0

        for scenario in scenarios:
            client = Client()
            if scenario.user != "guest":
                client.force_login(users[scenario.user])

            reply, error = None, ""
            for index, message in enumerate(scenario.messages):
                response = client.post(
                    reverse("chat_api"),
                    data={"message": message.format(**context), "new_conversation": index == 0},
                    content_type="application/json",
                )
                data = response.json()
                if response.status_code != 200:
                    error = f"HTTP {response.status_code}: {data.get('error', '')}"
                    break
                reply = Reply(text=data["reply"], escalated=data["escalate"])

            if error:
                failed += 1
                self.stdout.write(self.style.ERROR(f"FAIL  {scenario.name}  ({error})"))
                continue

            results = run_checks(scenario, reply, context)
            passed = all(result.passed for result in results)
            if passed:
                self.stdout.write(self.style.SUCCESS(f"PASS  {scenario.name}"))
            else:
                failed += 1
                self.stdout.write(self.style.ERROR(f"FAIL  {scenario.name}"))
                for result in results:
                    if not result.passed:
                        self.stdout.write(f"      expected: {result.description}")
            if show_replies or not passed:
                flag = " [escalated]" if reply.escalated else ""
                self.stdout.write(f"      reply{flag}: {reply.text}")
                last_log = ChatLog.objects.order_by("-id").first()
                tools = ", ".join(c.get("name", "?") for c in (last_log.tool_calls if last_log else []))
                self.stdout.write(f"      tools: {tools or 'none'}")

        self._summary(len(scenarios), failed)
        return failed

    def _summary(self, total: int, failed: int) -> None:
        logs = ChatLog.objects.all()
        tokens = sum(log.total_tokens or 0 for log in logs)
        cost = sum((log.estimated_cost_usd or 0 for log in logs), 0)
        latencies = [log.latency_ms for log in logs if log.latency_ms is not None]
        avg_latency = round(sum(latencies) / len(latencies)) if latencies else 0
        tool_calls = sum(len(log.tool_calls or []) for log in logs)

        self.stdout.write("")
        line = f"{total - failed}/{total} passed"
        self.stdout.write(self.style.SUCCESS(line) if not failed else self.style.ERROR(line))
        self.stdout.write(
            f"{logs.count()} messages | {tool_calls} tool calls | {tokens} tokens | est. ${cost:.4f} | "
            f"avg response {avg_latency} ms | model {MODEL}"
        )


def _create_eval_data():
    """Products, customers and an order with known values for the checks."""
    products = {p["name"]: Product.objects.create(**p) for p in EVAL_PRODUCTS}

    customer = User.objects.create_user("eval_customer", password=None)
    new_customer = User.objects.create_user("eval_new_customer", password=None)

    order = Order.objects.create(customer=customer, status=EVAL_ORDER["status"])
    product = products[EVAL_ORDER["product"]]
    OrderItem.objects.create(
        order=order,
        product=product,
        quantity=EVAL_ORDER["quantity"],
        price_at_purchase=product.price,
    )

    users = {"customer": customer, "new_customer": new_customer}
    context = {"order_id": order.pk}
    return users, context
