from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0003_more_products"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="product",
            constraint=models.CheckConstraint(
                condition=models.Q(stock__gte=0), name="store_product_stock_non_negative"
            ),
        ),
    ]
