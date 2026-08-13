from django.db import migrations

PRODUCTS = [
    (
        "Standing Desk Converter",
        "Sits on your existing desk and lifts your monitor and keyboard to standing height in one motion.",
        "179.00",
        15,
    ),
    (
        "Monitor Arm",
        "Single-monitor gas-spring arm. Clamps to desks up to 3in thick, full tilt/swivel/rotate.",
        "64.99",
        22,
    ),
    (
        "LED Desk Lamp",
        "Stepless dimming, adjustable color temperature, USB-C passthrough charging port on the base.",
        "44.99",
        35,
    ),
    (
        "Noise-Cancelling Headphones",
        "Over-ear ANC headphones, 30-hour battery, built for long focus sessions.",
        "129.00",
        18,
    ),
    (
        "Cable Management Tray",
        "Under-desk mount to keep power strips and cables off the floor and out of sight.",
        "18.99",
        60,
    ),
]


def seed_more_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for name, description, price, stock in PRODUCTS:
        Product.objects.create(
            name=name, description=description, price=price, stock=stock
        )


def remove_more_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Product.objects.filter(name__in=[p[0] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):

    dependencies = [("store", "0002_seed_products")]

    operations = [migrations.RunPython(seed_more_products, remove_more_products)]
