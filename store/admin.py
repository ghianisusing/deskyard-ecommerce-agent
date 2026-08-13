from django.contrib import admin
from django.utils.html import format_html

from .models import Order, OrderItem, Product


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "stock", "image_thumbnail")
    list_filter = ("category",)
    search_fields = ("name",)
    readonly_fields = ("image_preview",)
    fields = (
        "name",
        "description",
        "category",
        "price",
        "stock",
        "image",
        "image_preview",
    )

    @admin.display(description="Image")
    def image_thumbnail(self, obj):
        if not obj.image:
            return "—"
        return format_html(
            '<img src="{}" style="height:36px;width:36px;object-fit:cover;'
            'border-radius:4px;" />',
            obj.image.url,
        )

    @admin.display(description="Preview")
    def image_preview(self, obj):
        if not obj.image:
            return "No image uploaded — the storefront will fall back to the wireframe icon."
        return format_html(
            '<img src="{}" style="max-height:220px;max-width:220px;'
            'object-fit:cover;border-radius:6px;" />',
            obj.image.url,
        )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer", "status", "created_at")
    list_filter = ("status",)
    inlines = [OrderItemInline]
