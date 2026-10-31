from decimal import Decimal

from django.conf import settings
from django.db import models


class Product(models.Model):
    CATEGORY_CHOICES = [
        ("input", "Input Devices"),
        ("ergonomics", "Ergonomics"),
        ("audio_video", "Audio & Video"),
        ("lighting", "Lighting"),
        ("cable_management", "Cable Management"),
        ("accessories", "Accessories"),
        ("other", "Other"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="other", blank=True)
    image = models.ImageField(upload_to="products/", blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(stock__gte=0), name="store_product_stock_non_negative")
        ]

    def __str__(self):
        return self.name


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("shipped", "Shipped"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]

    # Kept separate from shipping status: per the store policy, payment is
    # taken when the order ships, so a pending order is normally unpaid.
    PAYMENT_STATUS_CHOICES = [
        ("unpaid", "Unpaid"),
        ("paid", "Paid"),
        ("refunded", "Refunded"),
    ]

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="unpaid")
    created_at = models.DateTimeField(auto_now_add=True)

    # Saved at checkout from the line items, so the amount a customer was
    # quoted never changes afterward.
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    # Required at checkout (see ShippingAddressForm). Blank only on orders
    # placed before addresses were collected.
    shipping_name = models.CharField("full name", max_length=200, blank=True)
    shipping_line1 = models.CharField("address", max_length=200, blank=True)
    shipping_line2 = models.CharField("apartment, suite, etc.", max_length=200, blank=True)
    shipping_city = models.CharField("city", max_length=100, blank=True)
    shipping_region = models.CharField("state / province", max_length=100, blank=True)
    shipping_postal_code = models.CharField("postal code", max_length=20, blank=True)
    shipping_country = models.CharField("country", max_length=100, blank=True)

    SHIPPING_FIELDS = [
        "shipping_name",
        "shipping_line1",
        "shipping_line2",
        "shipping_city",
        "shipping_region",
        "shipping_postal_code",
        "shipping_country",
    ]

    def __str__(self):
        return f"Order #{self.pk} ({self.customer})"

    def calculate_total(self) -> Decimal:
        """Sum of the line items at their purchase prices. Checkout stores
        this in `total`; use the field everywhere else."""
        return sum((item.subtotal() for item in self.items.all()), Decimal("0.00"))

    def shipping_address_lines(self) -> list[str]:
        """The address as display lines, skipping empty parts. Empty for
        orders placed before addresses were collected."""
        city_line = " ".join(
            part
            for part in (
                ", ".join(p for p in (self.shipping_city, self.shipping_region) if p),
                self.shipping_postal_code,
            )
            if part
        )
        lines = [
            self.shipping_name,
            self.shipping_line1,
            self.shipping_line2,
            city_line,
            self.shipping_country,
        ]
        return [line for line in lines if line]


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    price_at_purchase = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.quantity}x {self.product} (order #{self.order_id})"

    def subtotal(self):
        return self.price_at_purchase * self.quantity
