from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
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


class OrderTotalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bob", password="testpass123")

    def test_order_total_sums_item_subtotals(self):
        order = Order.objects.create(customer=self.user, status="pending")
        product_a = Product.objects.create(name="A", price=Decimal("10.00"), stock=10)
        product_b = Product.objects.create(name="B", price=Decimal("3.50"), stock=10)

        OrderItem.objects.create(order=order, product=product_a, quantity=2, price_at_purchase=Decimal("10.00"))
        OrderItem.objects.create(order=order, product=product_b, quantity=3, price_at_purchase=Decimal("3.50"))

        # 2 * 10.00 + 3 * 3.50 = 20.00 + 10.50 = 30.50
        self.assertEqual(order.total(), Decimal("30.50"))

    def test_order_total_is_zero_with_no_items(self):
        order = Order.objects.create(customer=self.user, status="pending")
        self.assertEqual(order.total(), 0)

    def test_order_total_reflects_price_at_purchase_not_current_price(self):
        order = Order.objects.create(customer=self.user, status="pending")
        product = Product.objects.create(name="C", price=Decimal("100.00"), stock=10)
        OrderItem.objects.create(order=order, product=product, quantity=1, price_at_purchase=Decimal("8.00"))

        # Price changed after purchase — order total should use the
        # snapshotted price, not today's product price.
        product.price = Decimal("100.00")
        product.save()

        self.assertEqual(order.total(), Decimal("8.00"))
