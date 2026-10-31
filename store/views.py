from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ShippingAddressForm
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


def _render_cart(request, address_form=None, status=200):
    lines = _cart_lines(request)
    if address_form is None and request.user.is_authenticated:
        address_form = ShippingAddressForm(initial=ShippingAddressForm.initial_for(request.user))
    context = {"items": lines, "total": _cart_total(lines), "address_form": address_form}
    return render(request, "store/cart.html", context, status=status)


def view_cart(request):
    return _render_cart(request)


def _stock_error(product_id: int, quantity: int) -> str:
    """Explain why a cart line couldn't be decremented."""
    product = Product.objects.filter(pk=product_id).first()
    if product is None:
        return (
            "An item in your cart is no longer available and has been removed. "
            "Please review your cart and try again."
        )
    return f"Only {product.stock} left of '{product.name}' (you have {quantity} in your cart)."


@login_required
def checkout(request):
    # Placing an order must never happen on GET, or any page could trigger
    # one with a link or <img>. A GET lands here after the login redirect
    # (?next=/checkout/), so send the customer back to their cart instead
    # of showing a bare 405.
    if request.method != "POST":
        return redirect("view_cart")

    cart = _get_cart(request)
    if not cart:
        return redirect("view_cart")

    # Check the address before reserving any stock.
    address_form = ShippingAddressForm(request.POST)
    if not address_form.is_valid():
        return _render_cart(request, address_form=address_form, status=400)

    try:
        with transaction.atomic():
            # Each line decrements stock with one conditional UPDATE
            # ("... SET stock = stock - n WHERE id = x AND stock >= n").
            # The database checks and decrements in a single step, so two
            # checkouts racing for the last unit can't both succeed on any
            # backend, SQLite included, without relying on
            # select_for_update() (a no-op on SQLite). If any line fails,
            # raising inside atomic() rolls back every decrement made so
            # far, so there is never a partial order.
            #
            # Lines go in a consistent pk order so two checkouts with
            # overlapping carts take row locks in the same sequence and
            # can't deadlock each other on Postgres/MySQL.
            line_items = sorted(((int(pk), qty) for pk, qty in cart.items()), key=lambda line: line[0])
            for product_id, quantity in line_items:
                decremented = Product.objects.filter(pk=product_id, stock__gte=quantity).update(
                    stock=F("stock") - quantity
                )
                if not decremented:
                    raise ValueError(_stock_error(product_id, quantity))

            products = Product.objects.in_bulk([product_id for product_id, _ in line_items])
            items = [
                OrderItem(
                    product=products[product_id],
                    quantity=quantity,
                    price_at_purchase=products[product_id].price,
                )
                for product_id, quantity in line_items
            ]
            order = address_form.save(commit=False)
            order.customer = request.user
            order.status = "pending"
            order.total = sum((item.subtotal() for item in items), Decimal("0.00"))
            order.save()
            for item in items:
                item.order = order
            OrderItem.objects.bulk_create(items)
    except ValueError as exc:
        messages.error(request, str(exc))
        # view_cart prunes any deleted products from the session.
        return redirect("view_cart")

    request.session["cart"] = {}
    request.session.modified = True
    order = Order.objects.prefetch_related("items__product").get(pk=order.pk)
    return render(request, "store/order_confirmation.html", {"order": order})


@login_required
def order_history(request):
    # The template lists every item and its product name; prefetch them so
    # the page costs the same few queries however many orders there are.
    orders = request.user.orders.prefetch_related("items__product").order_by("-created_at")
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
