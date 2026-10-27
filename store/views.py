from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Order, OrderItem, Product

PRODUCTS_PER_PAGE = 9


def _get_cart(request):
    return request.session.setdefault("cart", {})  # {product_id_str: quantity}


def _is_ajax(request) -> bool:
    # Set by the fetch() calls in cart.js. Plain <form> submissions (no JS,
    # or JS disabled) never send this header, so those still get the
    # original full-page redirect — this is progressive enhancement, not a
    # hard requirement on JavaScript being enabled.
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _cart_lines(request) -> list[dict]:
    """Load every product in the cart with one query. Lines whose product
    no longer exists (deleted in the admin) are dropped from the session
    instead of 404ing the whole cart page forever."""
    cart = _get_cart(request)
    products = Product.objects.in_bulk([int(pk) for pk in cart.keys()])

    lines = []
    for product_id, quantity in list(cart.items()):
        product = products.get(int(product_id))
        if product is None:
            del cart[product_id]
            request.session.modified = True
            continue
        lines.append({"product": product, "quantity": quantity, "subtotal": product.price * quantity})
    return lines


def _cart_total(lines: list[dict]) -> Decimal:
    return sum((line["subtotal"] for line in lines), Decimal("0.00"))


def product_list(request):
    products = Product.objects.all().order_by("name")

    query = request.GET.get("q", "").strip()
    if query:
        products = products.filter(Q(name__icontains=query) | Q(description__icontains=query))

    category = request.GET.get("category", "").strip()
    if category:
        products = products.filter(category=category)

    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Preserve the current search/category filters across pagination links
    # without stacking a "page" param onto itself.
    querystring = request.GET.copy()
    querystring.pop("page", None)

    return render(
        request,
        "store/product_list.html",
        {
            "products": page_obj,
            "page_obj": page_obj,
            "query": query,
            "selected_category": category,
            "categories": Product.CATEGORY_CHOICES,
            "querystring": querystring.urlencode(),
        },
    )


def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    return render(request, "store/product_detail.html", {"product": product})


@require_POST
def add_to_cart(request, pk):
    product = get_object_or_404(Product, pk=pk)
    try:
        quantity = max(int(request.POST.get("quantity", 1)), 1)
    except (TypeError, ValueError):
        quantity = 1
    cart = _get_cart(request)
    cart[str(pk)] = cart.get(str(pk), 0) + quantity
    request.session.modified = True

    if _is_ajax(request):
        return JsonResponse(
            {
                "ok": True,
                "cart_count": sum(cart.values()),
                "product_id": pk,
                "product_name": product.name,
                "quantity_added": quantity,
                "line_quantity": cart[str(pk)],
            }
        )
    return redirect("view_cart")


@require_POST
def remove_from_cart(request, pk):
    cart = _get_cart(request)
    cart.pop(str(pk), None)
    request.session.modified = True

    if _is_ajax(request):
        lines = _cart_lines(request)
        return JsonResponse(
            {
                "ok": True,
                "cart_count": sum(cart.values()),
                "removed_product_id": pk,
                "total": str(_cart_total(lines)),
                "cart_empty": len(cart) == 0,
            }
        )
    return redirect("view_cart")


def view_cart(request):
    lines = _cart_lines(request)
    return render(request, "store/cart.html", {"items": lines, "total": _cart_total(lines)})


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
            #
            # select_for_update() locks each product row for the duration of
            # this transaction, so two concurrent checkouts on the same
            # product can't both pass the stock check before either
            # decrements it. Iterate in a consistent pk order (not cart
            # insertion order) so two checkouts with overlapping carts
            # always acquire locks in the same sequence — otherwise you can
            # get a classic A-locks-1-then-2 / B-locks-2-then-1 deadlock.
            #
            # Note: select_for_update() is a no-op on SQLite (this project's
            # default DATABASES engine) — Django accepts the call but SQLite
            # has no real row-level locking, so this only takes effect once
            # the database is Postgres or MySQL.
            products = {}
            for product_id in sorted(cart.keys(), key=int):
                product = Product.objects.select_for_update().filter(pk=product_id).first()
                if product is None:
                    raise ValueError(
                        "An item in your cart is no longer available and has "
                        "been removed. Please review your cart and try again."
                    )
                quantity = cart[product_id]
                if quantity > product.stock:
                    raise ValueError(
                        f"Only {product.stock} left of '{product.name}' (you have {quantity} in your cart)."
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
        # view_cart prunes any deleted products from the session.
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
