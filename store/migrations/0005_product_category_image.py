from django.db import migrations, models

# Maps each existing seed product (from 0002/0003) to a sensible category so
# the new category filter has real data on day one instead of everything
# defaulting to "Other".
CATEGORY_BACKFILL = {
    "Wireless Mouse": "input",
    "Mechanical Keyboard": "input",
    "USB-C Hub": "accessories",
    "Laptop Stand": "ergonomics",
    "1080p Webcam": "audio_video",
    "Standing Desk Converter": "ergonomics",
    "Monitor Arm": "ergonomics",
    "LED Desk Lamp": "lighting",
    "Noise-Cancelling Headphones": "audio_video",
    "Cable Management Tray": "cable_management",
}


def backfill_categories(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for name, category in CATEGORY_BACKFILL.items():
        Product.objects.filter(name=name).update(category=category)


def reset_categories(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Product.objects.filter(name__in=CATEGORY_BACKFILL.keys()).update(category="other")


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0004_product_stock_non_negative"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="category",
            field=models.CharField(
                blank=True,
                choices=[
                    ("input", "Input Devices"),
                    ("ergonomics", "Ergonomics"),
                    ("audio_video", "Audio & Video"),
                    ("lighting", "Lighting"),
                    ("cable_management", "Cable Management"),
                    ("accessories", "Accessories"),
                    ("other", "Other"),
                ],
                default="other",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="image",
            field=models.ImageField(blank=True, null=True, upload_to="products/"),
        ),
        migrations.RunPython(backfill_categories, reset_categories),
    ]
