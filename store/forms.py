from django import forms

from .models import Order

# The model allows blank addresses (older orders have none); checkout
# doesn't. These are the parts a customer must fill in.
REQUIRED_SHIPPING_FIELDS = {
    "shipping_name",
    "shipping_line1",
    "shipping_city",
    "shipping_postal_code",
    "shipping_country",
}

AUTOCOMPLETE = {
    "shipping_name": "name",
    "shipping_line1": "address-line1",
    "shipping_line2": "address-line2",
    "shipping_city": "address-level2",
    "shipping_region": "address-level1",
    "shipping_postal_code": "postal-code",
    "shipping_country": "country-name",
}


class ShippingAddressForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = Order.SHIPPING_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.required = name in REQUIRED_SHIPPING_FIELDS
            field.widget.attrs["autocomplete"] = AUTOCOMPLETE[name]
            field.strip = True

    @classmethod
    def initial_for(cls, user) -> dict:
        """Pre-fill from the customer's most recent order that has an address."""
        last = user.orders.exclude(shipping_line1="").order_by("-created_at").first()
        if last is None:
            return {}
        return {name: getattr(last, name) for name in Order.SHIPPING_FIELDS}
