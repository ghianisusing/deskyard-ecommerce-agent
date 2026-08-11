from django.db import migrations

PRODUCTS = [
    ("Wireless Mouse", "Ergonomic wireless mouse with USB receiver.", "19.99", 50),
    ("Mechanical Keyboard", "Compact mechanical keyboard, blue switches.", "59.99", 30),
    ("USB-C Hub", "7-in-1 USB-C hub with HDMI and SD card reader.", "34.99", 40),
    ("Laptop Stand", "Adjustable aluminum laptop stand.", "24.99", 25),
    ("1080p Webcam", "Full HD webcam with built-in microphone.", "39.99", 20),
]


def seed_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    for name, description, price, stock in PRODUCTS:
        Product.objects.create(
            name=name, description=description, price=price, stock=stock
        )


def remove_products(apps, schema_editor):
    Product = apps.get_model("store", "Product")
    Product.objects.filter(name__in=[p[0] for p in PRODUCTS]).delete()


class Migration(migrations.Migration):

    dependencies = [("store", "0001_initial")]

    operations = [migrations.RunPython(seed_products, remove_products)]
