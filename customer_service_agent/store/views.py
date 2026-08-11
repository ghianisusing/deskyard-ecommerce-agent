from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .models import Order, OrderItem, Product


def _get_cart(request):
    return request.session.setdefault("cart", {})  # {product_id_str: quantity}


def product_list(request):
    products = Product.objects.all()
    return render(request, "store/product_list.html", {"products": products})


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, "store/product_detail.html", {"product": product})


def add_to_cart(request, pk):
    get_object_or_404(Product, pk=pk)
    quantity = 1
    if request.method == "POST":
        try:
            quantity = max(int(request.POST.get("quantity", 1)), 1)
        except (TypeError, ValueError):
            quantity = 1
    cart = _get_cart(request)
    cart[str(pk)] = cart.get(str(pk), 0) + quantity
    request.session.modified = True
    return redirect("view_cart")


def remove_from_cart(request, pk):
    cart = _get_cart(request)
    cart.pop(str(pk), None)
    request.session.modified = True
    return redirect("view_cart")


def view_cart(request):
    cart = _get_cart(request)
    items = []
    total = Decimal("0.00")
    for product_id, quantity in cart.items():
        product = get_object_or_404(Product, pk=product_id)
        subtotal = product.price * quantity
        total += subtotal
        items.append({"product": product, "quantity": quantity, "subtotal": subtotal})
    return render(request, "store/cart.html", {"items": items, "total": total})


@login_required
def checkout(request):
    cart = _get_cart(request)
    if not cart:
        return redirect("view_cart")

    try:
        with transaction.atomic():
            # Validate every line has enough stock BEFORE creating anything,
            # so a failure partway through can't leave a partial order or
            # decrement stock for items that never get order rows.
            products = {}
            for product_id, quantity in cart.items():
                product = get_object_or_404(Product, pk=product_id)
                if quantity > product.stock:
                    raise ValueError(
                        f"Only {product.stock} left of '{product.name}' "
                        f"(you have {quantity} in your cart)."
                    )
                products[product_id] = product

            order = Order.objects.create(customer=request.user, status="pending")
            for product_id, quantity in cart.items():
                product = products[product_id]
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price_at_purchase=product.price,
                )
                product.stock -= quantity
                product.save()
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("view_cart")

    request.session["cart"] = {}
    request.session.modified = True
    return render(request, "store/order_confirmation.html", {"order": order})


@login_required
def order_history(request):
    orders = request.user.orders.all().order_by("-created_at")
    return render(request, "store/order_history.html", {"orders": orders})


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect("product_list")
    else:
        form = UserCreationForm()
    return render(request, "store/register.html", {"form": form})
