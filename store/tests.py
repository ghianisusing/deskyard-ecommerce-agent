import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, connection, connections
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Order, OrderItem, Product


class CheckoutStockTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="testpass123")
        self.client.login(username="alice", password="testpass123")
        self.product = Product.objects.create(
            name="Test Widget", description="", price=Decimal("10.00"), stock=3
        )

    def _add_to_cart(self, quantity):
        for _ in range(quantity):
            self.client.post(reverse("add_to_cart", args=[self.product.pk]))

    def test_checkout_succeeds_within_stock(self):
        self._add_to_cart(2)
        self.client.post(reverse("checkout"))

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 1)
        self.assertEqual(Order.objects.filter(customer=self.user).count(), 1)
        order = Order.objects.get(customer=self.user)
        self.assertEqual(OrderItem.objects.filter(order=order).count(), 1)
        self.assertEqual(OrderItem.objects.get(order=order).quantity, 2)

    def test_checkout_rejects_overselling(self):
        self._add_to_cart(5)  # only 3 in stock
        response = self.client.post(reverse("checkout"), follow=True)

        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 3, "stock must be untouched when checkout fails")
        self.assertEqual(Order.objects.filter(customer=self.user).count(), 0)
        self.assertContains(response, "Only 3 left")

    def test_checkout_does_not_partially_apply_on_failure(self):
        # Two products in the cart; the second one doesn't have enough
        # stock. Nothing should be created for either product.
        other_product = Product.objects.create(
            name="Second Widget", description="", price=Decimal("5.00"), stock=1
        )
        self._add_to_cart(1)  # ok
        self.client.post(reverse("add_to_cart", args=[other_product.pk]))
        self.client.post(reverse("add_to_cart", args=[other_product.pk]))  # 2 requested, only 1 in stock

        self.client.post(reverse("checkout"))

        self.product.refresh_from_db()
        other_product.refresh_from_db()
        self.assertEqual(self.product.stock, 3, "unaffected product's stock must not change either")
        self.assertEqual(other_product.stock, 1)
        self.assertEqual(Order.objects.count(), 0)


class CheckoutRaceConditionTests(TransactionTestCase):
    """Two customers checking out the last unit of stock at the same time
    must not both succeed. Uses TransactionTestCase (not TestCase) because
    regular TestCase wraps every test in an outer transaction that gets
    rolled back at the end — real concurrent transactions from separate
    threads/connections need actual commits to interact, which only
    TransactionTestCase allows.

    Only the checkout requests run concurrently. Logging in and filling the
    carts happens first, one after the other: that setup isn't what's under
    test, and SQLite's in-memory test database rejects concurrent writes
    outright ("database table is locked") instead of waiting.
    """

    def setUp(self):
        self.product = Product.objects.create(name="Limited Edition Widget", price=Decimal("10.00"), stock=1)
        self.clients = []
        for username in ("alice", "bob"):
            User.objects.create_user(username=username, password="testpass123")
            client = Client()
            client.login(username=username, password="testpass123")
            client.post(reverse("add_to_cart", args=[self.product.pk]))
            self.clients.append(client)

    def _checkout(self, client, barrier, errors, index):
        barrier.wait()  # release both checkouts at the same moment
        try:
            client.post(reverse("checkout"))
        except OperationalError:
            # SQLite's in-memory test database may refuse a concurrent write
            # (the stock update, or the session save after it) instead of
            # waiting. That's an artifact of the test database; the database
            # state checked below is what proves there's no oversell.
            pass
        except Exception as exc:  # noqa: BLE001 - surfaced as a test failure below
            errors[index] = exc
        finally:
            connections.close_all()

    def test_concurrent_checkouts_cannot_oversell_last_unit(self):
        errors = [None, None]
        barrier = threading.Barrier(2)
        threads = [
            threading.Thread(target=self._checkout, args=(client, barrier, errors, i))
            for i, client in enumerate(self.clients)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [None, None], "checkout raised an unexpected error")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 0, "stock must never go negative — overselling occurred")
        self.assertEqual(
            Order.objects.count(),
            1,
            "only one of the two simultaneous buyers should get the last unit",
        )


class OrderTotalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="testpass123")

    def test_order_total_sums_item_subtotals(self):
        order = Order.objects.create(customer=self.user, status="pending")
        product_a = Product.objects.create(name="A", price=Decimal("10.00"), stock=10)
        product_b = Product.objects.create(name="B", price=Decimal("3.50"), stock=10)

        OrderItem.objects.create(
            order=order, product=product_a, quantity=2, price_at_purchase=Decimal("10.00")
        )
        OrderItem.objects.create(
            order=order, product=product_b, quantity=3, price_at_purchase=Decimal("3.50")
        )

        # 2 * 10.00 + 3 * 3.50 = 20.00 + 10.50 = 30.50
        self.assertEqual(order.total(), Decimal("30.50"))

    def test_order_total_is_zero_with_no_items(self):
        order = Order.objects.create(customer=self.user, status="pending")
        total = order.total()
        self.assertIsInstance(total, Decimal)
        self.assertEqual(str(total), "0.00")

    def test_order_total_reflects_price_at_purchase_not_current_price(self):
        order = Order.objects.create(customer=self.user, status="pending")
        product = Product.objects.create(name="C", price=Decimal("100.00"), stock=10)
        OrderItem.objects.create(order=order, product=product, quantity=1, price_at_purchase=Decimal("8.00"))

        # Price changed after purchase — order total should use the
        # snapshotted price, not today's product price.
        product.price = Decimal("100.00")
        product.save()

        self.assertEqual(order.total(), Decimal("8.00"))


class ProductListSearchAndFilterTests(TestCase):
    def setUp(self):
        # The test DB is built by running all migrations, which includes
        # the data migrations that seed 10 real products (0002/0003). Clear
        # them so this class's assertions aren't fighting unrelated data.
        Product.objects.all().delete()
        self.mouse = Product.objects.create(
            name="Wireless Mouse",
            description="Ergonomic wireless mouse with USB receiver.",
            price=Decimal("19.99"),
            stock=10,
            category="input",
        )
        self.lamp = Product.objects.create(
            name="LED Desk Lamp",
            description="Stepless dimming desk lamp.",
            price=Decimal("44.99"),
            stock=5,
            category="lighting",
        )

    def test_search_matches_name(self):
        response = self.client.get(reverse("product_list"), {"q": "mouse"})
        products = list(response.context["products"])
        self.assertIn(self.mouse, products)
        self.assertNotIn(self.lamp, products)

    def test_search_matches_description(self):
        response = self.client.get(reverse("product_list"), {"q": "dimming"})
        products = list(response.context["products"])
        self.assertIn(self.lamp, products)
        self.assertNotIn(self.mouse, products)

    def test_search_is_case_insensitive(self):
        response = self.client.get(reverse("product_list"), {"q": "WIRELESS"})
        self.assertIn(self.mouse, list(response.context["products"]))

    def test_no_results_for_unmatched_search(self):
        response = self.client.get(reverse("product_list"), {"q": "nonexistent-xyz"})
        self.assertEqual(len(response.context["products"]), 0)
        self.assertContains(response, "No products match your filters")

    def test_category_filter(self):
        response = self.client.get(reverse("product_list"), {"category": "lighting"})
        products = list(response.context["products"])
        self.assertIn(self.lamp, products)
        self.assertNotIn(self.mouse, products)

    def test_search_and_category_combine(self):
        response = self.client.get(reverse("product_list"), {"q": "lamp", "category": "input"})
        # "lamp" matches nothing in the "input" category
        self.assertEqual(len(response.context["products"]), 0)

    def test_empty_search_param_returns_everything(self):
        response = self.client.get(reverse("product_list"), {"q": ""})
        products = list(response.context["products"])
        self.assertIn(self.mouse, products)
        self.assertIn(self.lamp, products)


class ProductListPaginationTests(TestCase):
    def setUp(self):
        Product.objects.all().delete()
        for i in range(23):
            Product.objects.create(name=f"Product {i:02d}", price=Decimal("9.99"), stock=1)

    def test_first_page_has_expected_count(self):
        response = self.client.get(reverse("product_list"))
        self.assertEqual(len(response.context["products"]), 9)
        self.assertEqual(response.context["page_obj"].paginator.num_pages, 3)

    def test_last_page_has_remainder(self):
        response = self.client.get(reverse("product_list"), {"page": 3})
        self.assertEqual(len(response.context["products"]), 5)  # 23 - 9 - 9

    def test_out_of_range_page_clamps_to_last_page(self):
        response = self.client.get(reverse("product_list"), {"page": 999})
        self.assertEqual(response.context["page_obj"].number, 3)

    def test_pagination_controls_only_render_with_multiple_pages(self):
        response = self.client.get(reverse("product_list"), {"q": "Product 00"})
        self.assertNotContains(response, "pagination")


class ProductImageFallbackTests(TestCase):
    """The storefront must never show a broken image: if no image is
    uploaded, it falls back to the hand-drawn SVG wireframe icon instead."""

    def setUp(self):
        Product.objects.all().delete()

    def test_product_without_image_renders_svg_fallback_on_list_page(self):
        Product.objects.create(name="Wireless Mouse", price=Decimal("19.99"), stock=5)
        response = self.client.get(reverse("product_list"))
        self.assertContains(response, "<svg")
        self.assertNotContains(response, "<img")

    def test_product_without_image_renders_svg_fallback_on_detail_page(self):
        product = Product.objects.create(name="Wireless Mouse", price=Decimal("19.99"), stock=5)
        response = self.client.get(reverse("product_detail", args=[product.pk]))
        self.assertContains(response, "<svg")
        self.assertNotContains(response, "<img")


def _make_test_png() -> bytes:
    """Build a minimal valid 1x1 PNG in memory so ImageField (which uses
    Pillow to validate uploads) accepts it without needing a real asset
    file checked into the repo."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 229, 0)).save(buf, format="PNG")
    return buf.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProductImageUploadTests(TestCase):
    """Uses an isolated temp MEDIA_ROOT (cleaned up in tearDownClass) so
    running this test never writes into the project's real media/
    directory."""

    def setUp(self):
        Product.objects.all().delete()

    @classmethod
    def tearDownClass(cls):
        from django.conf import settings

        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_product_with_image_renders_img_tag_on_list_page(self):
        product = Product.objects.create(name="Wireless Mouse", price=Decimal("19.99"), stock=5)
        product.image.save("mouse.png", SimpleUploadedFile("mouse.png", _make_test_png(), "image/png"))

        response = self.client.get(reverse("product_list"))
        self.assertContains(response, "<img")
        self.assertContains(response, product.image.url)

    def test_product_with_image_renders_img_tag_on_detail_page(self):
        product = Product.objects.create(name="Wireless Mouse", price=Decimal("19.99"), stock=5)
        product.image.save("mouse.png", SimpleUploadedFile("mouse.png", _make_test_png(), "image/png"))

        response = self.client.get(reverse("product_detail", args=[product.pk]))
        self.assertContains(response, "<img")
        self.assertContains(response, product.image.url)


class CartAjaxTests(TestCase):
    """cart.js sends X-Requested-With: XMLHttpRequest so the view can
    respond with JSON and update the page in place instead of the browser
    doing a full navigation. Plain form submissions (no JS, or JS failed to
    load) never send that header, so they must still get the original
    redirect — this class checks both paths for both endpoints."""

    def setUp(self):
        self.product = Product.objects.create(name="Wireless Mouse", price=Decimal("20.00"), stock=10)
        self.other_product = Product.objects.create(name="USB-C Hub", price=Decimal("15.00"), stock=10)

    def test_add_to_cart_ajax_returns_json_without_redirecting(self):
        response = self.client.post(
            reverse("add_to_cart", args=[self.product.pk]),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["cart_count"], 2)
        self.assertEqual(data["line_quantity"], 2)
        self.assertEqual(data["quantity_added"], 2)
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 2})

    def test_add_to_cart_without_ajax_header_still_redirects(self):
        response = self.client.post(reverse("add_to_cart", args=[self.product.pk]), {"quantity": 1})
        self.assertRedirects(response, reverse("view_cart"))

    def test_add_to_cart_ajax_accumulates_existing_quantity(self):
        self.client.post(
            reverse("add_to_cart", args=[self.product.pk]),
            {"quantity": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        response = self.client.post(
            reverse("add_to_cart", args=[self.product.pk]),
            {"quantity": 3},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertEqual(data["line_quantity"], 4)
        self.assertEqual(data["cart_count"], 4)

    def test_remove_from_cart_ajax_returns_json_with_updated_total(self):
        self.client.post(
            reverse("add_to_cart", args=[self.product.pk]),
            {"quantity": 2},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.client.post(
            reverse("add_to_cart", args=[self.other_product.pk]),
            {"quantity": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        response = self.client.post(
            reverse("remove_from_cart", args=[self.product.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["cart_empty"])
        self.assertEqual(data["total"], "15.00")  # only the hub remains
        self.assertEqual(data["cart_count"], 1)

    def test_remove_from_cart_ajax_reports_empty_cart(self):
        self.client.post(
            reverse("add_to_cart", args=[self.product.pk]),
            {"quantity": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        response = self.client.post(
            reverse("remove_from_cart", args=[self.product.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()
        self.assertTrue(data["cart_empty"])
        self.assertEqual(data["cart_count"], 0)

    def test_remove_from_cart_without_ajax_header_still_redirects(self):
        self.client.post(reverse("add_to_cart", args=[self.product.pk]), {"quantity": 1})
        response = self.client.post(reverse("remove_from_cart", args=[self.product.pk]))
        self.assertRedirects(response, reverse("view_cart"))


class DeletedProductInCartTests(TestCase):
    """A product deleted in the admin used to 404 the cart page forever for
    anyone who had it in their session."""

    def setUp(self):
        self.user = User.objects.create_user(username="carol", password="testpass123")
        self.client.login(username="carol", password="testpass123")
        self.kept = Product.objects.create(name="Desk Mat", price=Decimal("12.00"), stock=5)
        self.doomed = Product.objects.create(name="Old Lamp", price=Decimal("30.00"), stock=5)
        self.client.post(reverse("add_to_cart", args=[self.kept.pk]))
        self.client.post(reverse("add_to_cart", args=[self.doomed.pk]))
        self.doomed.delete()

    def test_cart_still_loads_and_drops_the_missing_line(self):
        response = self.client.get(reverse("view_cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Desk Mat")
        self.assertNotContains(response, "Old Lamp")
        self.assertEqual(response.context["total"], Decimal("12.00"))
        self.assertEqual(self.client.session["cart"], {str(self.kept.pk): 1})

    def test_checkout_redirects_with_a_message_instead_of_404(self):
        response = self.client.post(reverse("checkout"), follow=True)
        self.assertRedirects(response, reverse("view_cart"))
        self.assertContains(response, "no longer available")
        self.assertFalse(Order.objects.exists())
        self.kept.refresh_from_db()
        self.assertEqual(self.kept.stock, 5)


class CartQueryCountTests(TestCase):
    def test_product_queries_do_not_grow_with_cart_size(self):
        def product_queries_for_cart_page():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(reverse("view_cart"))
            return [q for q in ctx.captured_queries if "store_product" in q["sql"]]

        first = Product.objects.create(name="Item 0", price=Decimal("1.00"), stock=5)
        self.client.post(reverse("add_to_cart", args=[first.pk]))
        baseline = len(product_queries_for_cart_page())

        for i in range(1, 6):
            product = Product.objects.create(name=f"Item {i}", price=Decimal("1.00"), stock=5)
            self.client.post(reverse("add_to_cart", args=[product.pk]))

        self.assertEqual(len(product_queries_for_cart_page()), baseline)


class CartRequiresPostTests(TestCase):
    """Cart changes must not happen on GET, or any page could add items to
    a visitor's cart with an image tag or a link."""

    def setUp(self):
        self.product = Product.objects.create(name="Mouse", price=Decimal("20.00"), stock=5)

    def test_get_cannot_add_to_cart(self):
        response = self.client.get(reverse("add_to_cart", args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.session.get("cart", {}), {})

    def test_get_cannot_remove_from_cart(self):
        self.client.post(reverse("add_to_cart", args=[self.product.pk]))
        response = self.client.get(reverse("remove_from_cart", args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 1})


class CheckoutRequiresPostTests(TestCase):
    """GET /checkout/ must never place an order, or a link or image on any
    page could buy things on a logged-in customer's behalf."""

    def setUp(self):
        User.objects.create_user(username="dave", password="testpass123")
        self.product = Product.objects.create(name="Monitor Arm", price=Decimal("50.00"), stock=5)

    def test_get_redirects_to_cart_without_ordering(self):
        self.client.login(username="dave", password="testpass123")
        self.client.post(reverse("add_to_cart", args=[self.product.pk]))

        response = self.client.get(reverse("checkout"))

        self.assertRedirects(response, reverse("view_cart"))
        self.assertFalse(Order.objects.exists())
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 1})

    def test_guest_is_sent_to_login_then_back_to_cart(self):
        self.client.post(reverse("add_to_cart", args=[self.product.pk]))
        response = self.client.post(reverse("checkout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

        # After logging in, the ?next= redirect is a GET: back to the cart.
        self.client.login(username="dave", password="testpass123")
        self.assertRedirects(self.client.get(reverse("checkout")), reverse("view_cart"))


class RegistrationPasswordRulesTests(TestCase):
    def test_weak_password_is_rejected(self):
        response = self.client.post(
            reverse("register"), {"username": "erin", "password1": "12345", "password2": "12345"}
        )
        self.assertEqual(response.status_code, 200)  # form re-rendered with errors
        self.assertFalse(User.objects.filter(username="erin").exists())

    def test_strong_password_is_accepted(self):
        password = "plum-orbit-castle-91"
        self.client.post(
            reverse("register"), {"username": "erin", "password1": password, "password2": password}
        )
        self.assertTrue(User.objects.filter(username="erin").exists())


class SecurityHeadersTests(TestCase):
    def test_pages_cannot_be_framed_and_sniffing_is_off(self):
        response = self.client.get(reverse("product_list"))
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")


class ProductionSettingsGuardTests(SimpleTestCase):
    """Settings are module-level, so check the guard in a fresh process."""

    def _load_settings(self, **env):
        full_env = {**os.environ, **env}
        return subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            env={**full_env, "DJANGO_SETTINGS_MODULE": "csa_project.settings"},
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_refuses_to_start_without_secret_key_when_debug_is_off(self):
        # Empty strings (not missing keys) so python-dotenv won't fill them from .env.
        result = self._load_settings(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY must be set", result.stderr)

    def test_starts_with_secret_key_when_debug_is_off(self):
        result = self._load_settings(DJANGO_DEBUG="False", DJANGO_SECRET_KEY="a-real-secret")
        self.assertEqual(result.returncode, 0, result.stderr)


def _place_order(customer, products, quantity=1):
    order = Order.objects.create(customer=customer, status="pending")
    for product in products:
        OrderItem.objects.create(
            order=order, product=product, quantity=quantity, price_at_purchase=product.price
        )
    return order


class OrderQueryCountTests(TestCase):
    """Pages that list orders must not run extra queries per order or per
    item, or they slow down as a customer's history grows."""

    def setUp(self):
        self.user = User.objects.create_user(username="frank", password="testpass123")
        self.client.login(username="frank", password="testpass123")
        self.products = [
            Product.objects.create(name=f"Gadget {i}", price=Decimal("5.00"), stock=100) for i in range(4)
        ]

    def _count_queries(self, fn):
        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)

    def test_order_history_query_count_does_not_grow_with_orders(self):
        _place_order(self.user, self.products[:1])
        baseline = self._count_queries(lambda: self.client.get(reverse("order_history")))

        for _ in range(4):
            _place_order(self.user, self.products)

        response_queries = self._count_queries(lambda: self.client.get(reverse("order_history")))
        self.assertEqual(response_queries, baseline)

    def test_order_history_still_shows_items_and_totals(self):
        _place_order(self.user, self.products[:2], quantity=3)
        response = self.client.get(reverse("order_history"))
        self.assertContains(response, "3 &times; Gadget 0")
        self.assertContains(response, "3 &times; Gadget 1")
        self.assertContains(response, "$30.00")

    def test_order_confirmation_loads_items_in_one_query(self):
        for product in self.products:
            self.client.post(reverse("add_to_cart", args=[product.pk]))

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, 200)
        for product in self.products:
            self.assertContains(response, product.name)
        item_selects = [
            q for q in ctx.captured_queries if q["sql"].startswith("SELECT") and "store_orderitem" in q["sql"]
        ]
        self.assertEqual(len(item_selects), 1)
