from django.db import migrations

INITIAL_ENTRIES = [
    (
        "Shipping",
        "Standard shipping takes 3-5 business days. Express shipping takes "
        "1-2 business days and costs $12.99. Free standard shipping on "
        "orders over $50.",
    ),
    (
        "Returns",
        "Items can be returned within 30 days of delivery for a full "
        "refund. Items must be unused and in original packaging. Refunds "
        "are processed within 5-7 business days after we receive the item.",
    ),
    (
        "Order status",
        "Customers can check order status by logging into their account "
        "and visiting 'My Orders'. Tracking numbers are emailed once an "
        "order ships.",
    ),
    (
        "Payment methods",
        "We accept Visa, Mastercard, American Express, PayPal, and Apple "
        "Pay. Payment is charged when the order ships, not when it's "
        "placed.",
    ),
    (
        "Contact / escalation",
        "If a customer is angry, asks for a refund on a damaged or wrong "
        "item, or explicitly asks for a human, escalate to a human agent "
        "instead of resolving it yourself.",
    ),
]


def seed_entries(apps, schema_editor):
    KnowledgeBaseEntry = apps.get_model("agent", "KnowledgeBaseEntry")
    for topic, content in INITIAL_ENTRIES:
        KnowledgeBaseEntry.objects.create(topic=topic, content=content)


def remove_entries(apps, schema_editor):
    KnowledgeBaseEntry = apps.get_model("agent", "KnowledgeBaseEntry")
    KnowledgeBaseEntry.objects.filter(
        topic__in=[topic for topic, _ in INITIAL_ENTRIES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [("agent", "0001_initial")]

    operations = [migrations.RunPython(seed_entries, remove_entries)]
