# apps/inventory/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Sum, F, Count
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
import datetime
import logging
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from accounts.models import Notification, User
from django.db.models import Q

from .models import Product, SaleUnit, Category, Unit, StockMovement, InventoryAlert
from tenants.models import Tenant

logger = logging.getLogger(__name__)


def user_can_view_inventory(user):
    """Check if user can view inventory"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'supervisor', 'viewer'])


def user_can_manage_inventory(user):
    """Check if user can manage inventory (create, edit, delete)"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'supervisor'])


# ==================== NOTIFICATION HELPER FUNCTIONS ====================

def send_expiry_notifications(product, days_until_expiry):
    """Send notifications and emails for expiring products"""
    tenant = product.tenant

    # Get all managers, admins, and supervisors in the tenant
    recipients = User.objects.filter(
        tenant=tenant,
        role__in=['admin', 'manager', 'supervisor'],
        is_active=True
    )

    title = f'⚠️ Product Expiring Soon: {product.name}'
    message = f'Product "{product.name}" will expire in {days_until_expiry} days. Expiry date: {product.expiry_date}. Current stock: {product.quantity} units. Please take action.'

    # Create notifications for all recipients
    for user in recipients:
        Notification.create_notification(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            notification_type='warning',
            category='inventory',
            link=f'/inventory/products/{product.id}/',
            link_text='View Product',
            icon='fa-clock'
        )

    # Send email notifications to all recipients
    send_expiry_email(product, days_until_expiry, recipients)

    # Also create a global notification for the tenant
    Notification.create_global_notification(
        tenant=tenant,
        title=f'⚠️ Product Expiring: {product.name}',
        message=f'{product.name} will expire in {days_until_expiry} days. Stock: {product.quantity} units.',
        notification_type='warning',
        category='inventory',
        link=f'/inventory/products/{product.id}/',
        link_text='View Product',
        icon='fa-clock'
    )

    return True


def send_expiry_email(product, days_until_expiry, recipients):
    """Send email notification for expiring products"""
    try:
        subject = f'⚠️ PharmaPro Alert: {product.name} Expiring Soon'

        context = {
            'product': product,
            'days_until_expiry': days_until_expiry,
            'expiry_date': product.expiry_date,
            'current_stock': product.quantity,
            'product_link': f'/inventory/products/{product.id}/',
            'site_name': 'PharmaPro',
            'tenant': product.tenant,
            'protocol': 'http',
            'domain': 'localhost:8000',
        }

        html_message = render_to_string('inventory/email/expiry_alert.html', context)
        plain_message = strip_tags(html_message)

        recipient_emails = [user.email for user in recipients if user.email]

        if recipient_emails:
            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                recipient_emails,
                html_message=html_message,
                fail_silently=False
            )
            logger.info(f"Expiry email sent for product {product.name}")
            return True
    except Exception as e:
        logger.error(f"Error sending expiry email: {str(e)}")
        return False


def send_low_stock_notification(product):
    """Send low stock notifications"""
    tenant = product.tenant

    recipients = User.objects.filter(
        tenant=tenant,
        role__in=['admin', 'manager', 'supervisor'],
        is_active=True
    )

    title = f'📦 Low Stock Alert: {product.name}'
    message = f'Product "{product.name}" is running low. Current stock: {product.quantity}, Reorder point: {product.reorder_point}. Please reorder soon.'

    # Create notifications
    for user in recipients:
        Notification.create_notification(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            notification_type='warning',
            category='inventory',
            link=f'/inventory/products/{product.id}/',
            link_text='View Product',
            icon='fa-exclamation-triangle'
        )

    # Send email
    try:
        subject = f'📦 Low Stock Alert: {product.name}'
        context = {
            'product': product,
            'current_stock': product.quantity,
            'reorder_point': product.reorder_point,
            'product_link': f'/inventory/products/{product.id}/',
            'site_name': 'PharmaPro',
            'tenant': product.tenant,
            'protocol': 'http',
            'domain': 'localhost:8000',
        }

        html_message = render_to_string('inventory/email/low_stock_alert.html', context)
        plain_message = strip_tags(html_message)

        recipient_emails = [user.email for user in recipients if user.email]

        if recipient_emails:
            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                recipient_emails,
                html_message=html_message,
                fail_silently=False
            )
    except Exception as e:
        logger.error(f"Error sending low stock email: {str(e)}")


# ==================== UPDATE check_product_alerts ====================

def check_product_alerts(product):
    """Check and create alerts for a product with notifications"""
    alerts_created = []
    from django.utils import timezone
    import datetime

    # Check for low stock
    if product.quantity <= product.reorder_point:
        if product.quantity > 0:
            alert_type = 'low_stock'
            severity = 'warning'
            message = f'Product "{product.name}" is running low. Current stock: {product.quantity}, Reorder point: {product.reorder_point}'
        else:
            alert_type = 'out_of_stock'
            severity = 'critical'
            message = f'Product "{product.name}" is out of stock!'

        if not InventoryAlert.objects.filter(
            product=product,
            alert_type=alert_type,
            is_read=False
        ).exists():
            alert = InventoryAlert.objects.create(
                tenant=product.tenant,
                product=product,
                alert_type=alert_type,
                severity=severity,
                message=message,
                is_read=False
            )
            alerts_created.append(alert)

            # Send low stock notification
            send_low_stock_notification(product)

    # Check for expiring products
    if product.expiry_date:
        if isinstance(product.expiry_date, str):
            from datetime import datetime
            expiry_date = datetime.strptime(product.expiry_date, '%Y-%m-%d').date()
        else:
            expiry_date = product.expiry_date

        days_until_expiry = (expiry_date - timezone.now().date()).days

        # Check for expiring in 30 days or less
        if 0 <= days_until_expiry <= 30 and product.quantity > 0:
            severity = 'warning' if days_until_expiry <= 7 else 'info'
            message = f'Product "{product.name}" expires in {days_until_expiry} days. Expiry date: {expiry_date}'

            alert, created = InventoryAlert.objects.get_or_create(
                product=product,
                alert_type='expiring',
                is_read=False,
                defaults={
                    'tenant': product.tenant,
                    'severity': severity,
                    'message': message,
                    'is_read': False
                }
            )

            if created:
                alerts_created.append(alert)
                # Send expiry notification
                send_expiry_notifications(product, days_until_expiry)
            else:
                # Update existing alert with new message if days changed
                if alert.message != message:
                    alert.message = message
                    alert.save()

    return alerts_created


# ==================== DASHBOARD VIEW ====================

@login_required
def dashboard_view(request):
    """Inventory dashboard - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    total_products = Product.objects.filter(tenant=tenant).count()
    low_stock = Product.objects.filter(
        tenant=tenant,
        quantity__lte=F('reorder_point'),
        quantity__gt=0
    ).count()
    out_of_stock = Product.objects.filter(tenant=tenant, quantity=0).count()
    total_categories = Category.objects.filter(tenant=tenant).count()
    total_units = Unit.objects.filter(tenant=tenant).count()

    stock_value = Product.objects.filter(tenant=tenant).aggregate(
        total=Sum(F('quantity') * F('purchase_price'))
    )['total'] or 0

    recent_movements = StockMovement.objects.filter(
        tenant=tenant
    ).select_related('product', 'created_by').order_by('-created_at')[:10]

    low_stock_products = Product.objects.filter(
        tenant=tenant,
        quantity__lte=F('reorder_point')
    ).select_related('category', 'unit').order_by('quantity')[:10]

    thirty_days_from_now = timezone.now().date() + datetime.timedelta(days=30)
    expiring_products = Product.objects.filter(
        tenant=tenant,
        expiry_date__isnull=False,
        expiry_date__lte=thirty_days_from_now,
        expiry_date__gte=timezone.now().date(),
        quantity__gt=0
    ).select_related('category', 'unit').order_by('expiry_date')[:10]

    # ===== SHOW ALL ALERTS (NOT JUST UNREAD) =====
    # Get all alerts ordered by created_at descending
    all_alerts = InventoryAlert.objects.filter(
        tenant=tenant
    ).order_by('-created_at')[:10]

    # Count active alerts (not resolved)
    active_alerts_count = InventoryAlert.objects.filter(
        tenant=tenant,
        is_resolved=False
    ).count()

    # For backward compatibility - keep recent_alerts as unread
    recent_alerts = InventoryAlert.objects.filter(
        tenant=tenant,
        is_read=False
    ).order_by('-created_at')[:5]

    # Get status distribution
    status_distribution = Product.objects.filter(
        tenant=tenant
    ).values('status').annotate(count=Count('id'))

    # Get product names for each status
    status_products = {}
    for status in status_distribution:
        status_key = status['status']
        products = Product.objects.filter(tenant=tenant, status=status_key).values_list('name', flat=True)[:10]
        status_products[status_key] = list(products)

    # Get top moved products in last 30 days
    thirty_days_ago = timezone.now() - datetime.timedelta(days=30)
    top_moved_products = StockMovement.objects.filter(
        tenant=tenant,
        created_at__gte=thirty_days_ago
    ).values('product__name').annotate(
        total_movements=Count('id'),
        total_quantity=Sum('quantity')
    ).order_by('-total_movements')[:5]

    context = {
        'total_products': total_products,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'total_categories': total_categories,
        'total_units': total_units,
        'stock_value': stock_value,
        'recent_movements': recent_movements,
        'low_stock_products': low_stock_products,
        'expiring_products': expiring_products,
        'recent_alerts': recent_alerts,
        'all_alerts': all_alerts,  # All alerts (including resolved)
        'active_alerts_count': active_alerts_count,  # Count of active alerts
        'status_distribution': status_distribution,
        'status_products': status_products,
        'top_moved_products': top_moved_products,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Inventory Dashboard - PharmaPro'
    }
    return render(request, 'inventory/dashboard.html', context)



@login_required
def product_list_view(request):
    """List all products - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    products = Product.objects.filter(tenant=tenant).select_related('category', 'unit')

    search_query = request.GET.get('search', '')
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(barcode__icontains=search_query) |
            Q(category__name__icontains=search_query)
        )

    category_filter = request.GET.get('category', '')
    if category_filter:
        products = products.filter(category_id=category_filter)

    status_filter = request.GET.get('status', '')
    if status_filter:
        products = products.filter(status=status_filter)

    stock_filter = request.GET.get('stock', '')
    if stock_filter == 'low':
        products = products.filter(quantity__lte=F('reorder_point'), quantity__gt=0)
    elif stock_filter == 'out':
        products = products.filter(quantity=0)
    elif stock_filter == 'in':
        products = products.filter(quantity__gt=0)

    products = products.order_by('-created_at')

    paginator = Paginator(products, 20)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)

    categories = Category.objects.filter(tenant=tenant)
    units = Unit.objects.filter(tenant=tenant)

    context = {
        'products': products_page,
        'categories': categories,
        'units': units,
        'search_query': search_query,
        'category_filter': category_filter,
        'status_filter': status_filter,
        'stock_filter': stock_filter,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Products - PharmaPro'
    }
    return render(request, 'inventory/products.html', context)


@login_required
def product_detail_view(request, product_id):
    """View product details - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)

    stock_movements = StockMovement.objects.filter(
        product=product,
        tenant=tenant
    ).select_related('created_by').order_by('-created_at')[:20]

    stock_in = StockMovement.objects.filter(
        product=product,
        movement_type='purchase'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    stock_out = StockMovement.objects.filter(
        product=product,
        movement_type='sale'
    ).aggregate(total=Sum('quantity'))['total'] or 0

    is_expiring_soon = False
    if product.expiry_date:
        days_until_expiry = (product.expiry_date - timezone.now().date()).days
        is_expiring_soon = days_until_expiry <= 30 and days_until_expiry >= 0

    context = {
        'product': product,
        'stock_movements': stock_movements,
        'stock_in': stock_in,
        'stock_out': stock_out,
        'is_expiring_soon': is_expiring_soon,
        'can_manage': user_can_manage_inventory(request.user),
        'title': f'{product.name} - PharmaPro'
    }
    return render(request, 'inventory/product_detail.html', context)


@login_required
def product_create_view(request):
    """Create a new product - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            sku = request.POST.get('sku', '').strip()

            if not name:
                messages.error(request, 'Product name is required.')
                return redirect('inventory:product_create')

            if not sku:
                messages.error(request, 'SKU is required.')
                return redirect('inventory:product_create')

            if Product.objects.filter(tenant=tenant, sku=sku).exists():
                messages.error(request, f'SKU "{sku}" already exists.')
                return redirect('inventory:product_create')

            expiry_date = request.POST.get('expiry_date') or None
            manufacturing_date = request.POST.get('manufacturing_date') or None

            product = Product.objects.create(
                tenant=tenant,
                name=name,
                sku=sku,
                barcode=request.POST.get('barcode', '').strip(),
                description=request.POST.get('description', '').strip(),
                category_id=request.POST.get('category') or None,
                unit_id=request.POST.get('unit') or None,
                purchase_price=Decimal(request.POST.get('purchase_price', 0) or 0),
                selling_price=Decimal(request.POST.get('selling_price', 0) or 0),
                wholesale_price=Decimal(request.POST.get('wholesale_price', 0) or 0),
                quantity=Decimal(request.POST.get('quantity', 0) or 0),
                min_quantity=Decimal(request.POST.get('min_quantity', 0) or 0),
                reorder_point=Decimal(request.POST.get('reorder_point', 0) or 0),
                reorder_quantity=Decimal(request.POST.get('reorder_quantity', 0) or 0),
                batch_number=request.POST.get('batch_number', '').strip(),
                expiry_date=expiry_date,
                manufacturing_date=manufacturing_date,
                location=request.POST.get('location', '').strip(),
                shelf_number=request.POST.get('shelf_number', '').strip(),
                status=request.POST.get('status', 'active'),
                created_by=request.user,
                is_active=True,
                allow_fractional=request.POST.get('allow_fractional') == 'on'
            )

            if request.FILES.get('image'):
                product.image = request.FILES.get('image')
                product.save()

            unit_names = request.POST.getlist('unit_names[]')
            unit_abbrs = request.POST.getlist('unit_abbrs[]')
            unit_quantities = request.POST.getlist('unit_quantities[]')
            unit_prices = request.POST.getlist('unit_prices[]')
            unit_costs = request.POST.getlist('unit_costs[]')
            default_unit_index = request.POST.get('default_unit')

            smallest_quantity = Decimal('999999')
            smallest_unit_name = ''
            smallest_abbr = ''

            for i in range(len(unit_names)):
                if not unit_names[i] or not unit_abbrs[i] or not unit_quantities[i] or not unit_prices[i]:
                    continue

                qty_per_unit = Decimal(unit_quantities[i] or 0)

                if qty_per_unit < smallest_quantity:
                    smallest_quantity = qty_per_unit
                    smallest_unit_name = unit_names[i].strip()
                    smallest_abbr = unit_abbrs[i].strip()

                is_default = (default_unit_index == str(i))

                SaleUnit.objects.create(
                    tenant=tenant,
                    product=product,
                    name=unit_names[i].strip(),
                    abbreviation=unit_abbrs[i].strip(),
                    quantity_per_unit=qty_per_unit,
                    selling_price=Decimal(unit_prices[i] or 0),
                    purchase_price=Decimal(unit_costs[i] if i < len(unit_costs) else 0),
                    is_default=is_default,
                    is_active=True
                )

            if smallest_unit_name:
                base_unit, created = Unit.objects.get_or_create(
                    tenant=tenant,
                    name=smallest_unit_name,
                    defaults={
                        'abbreviation': smallest_abbr,
                        'created_by': request.user
                    }
                )
                product.unit = base_unit
                product.save()

            if product.quantity > 0:
                StockMovement.objects.create(
                    tenant=tenant,
                    product=product,
                    movement_type='purchase',
                    quantity=product.quantity,
                    previous_quantity=Decimal(0),
                    new_quantity=product.quantity,
                    unit_price=product.purchase_price,
                    total_price=product.quantity * product.purchase_price,
                    reference='Initial stock',
                    notes=f'Initial stock in base units ({product.unit.name if product.unit else "units"})',
                    created_by=request.user
                )

            # Check for alerts after creation
            check_product_alerts(product)

            messages.success(request, f'Product "{product.name}" created successfully!')
            return redirect('inventory:product_detail', product_id=product.id)

        except Exception as e:
            messages.error(request, f'Error creating product: {str(e)}')
            logger.error(f"Product creation error: {str(e)}")

        return redirect('inventory:product_create')

    categories = Category.objects.filter(tenant=tenant)
    units = Unit.objects.filter(tenant=tenant)

    context = {
        'categories': categories,
        'units': units,
        'title': 'Create Product - PharmaPro'
    }
    return render(request, 'inventory/product_create.html', context)


@login_required
def product_edit_view(request, product_id):
    """Edit a product - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)

    if request.method == 'POST':
        try:
            new_sku = request.POST.get('sku', '').strip()
            if new_sku and new_sku != product.sku:
                if Product.objects.filter(tenant=tenant, sku=new_sku).exists():
                    messages.error(request, f'SKU "{new_sku}" already exists.')
                    return redirect('inventory:product_edit', product_id=product_id)

            product.name = request.POST.get('name', product.name).strip()
            product.sku = new_sku
            product.barcode = request.POST.get('barcode', product.barcode).strip()
            product.description = request.POST.get('description', product.description).strip()
            product.category_id = request.POST.get('category') or None

            product.purchase_price = Decimal(request.POST.get('purchase_price', product.purchase_price) or 0)
            product.selling_price = Decimal(request.POST.get('selling_price', product.selling_price) or 0)
            product.wholesale_price = Decimal(request.POST.get('wholesale_price', product.wholesale_price) or 0)
            product.min_quantity = Decimal(request.POST.get('min_quantity', product.min_quantity) or 0)
            product.reorder_point = Decimal(request.POST.get('reorder_point', product.reorder_point) or 0)
            product.reorder_quantity = Decimal(request.POST.get('reorder_quantity', product.reorder_quantity) or 0)

            product.allow_fractional = request.POST.get('allow_fractional') == 'on'
            product.batch_number = request.POST.get('batch_number', product.batch_number).strip()

            product.expiry_date = request.POST.get('expiry_date') or None
            product.manufacturing_date = request.POST.get('manufacturing_date') or None

            product.location = request.POST.get('location', product.location).strip()
            product.shelf_number = request.POST.get('shelf_number', product.shelf_number).strip()
            product.status = request.POST.get('status', product.status)

            new_quantity = Decimal(request.POST.get('quantity', product.quantity) or 0)

            if new_quantity != product.quantity:
                if new_quantity > product.quantity:
                    quantity_diff = new_quantity - product.quantity
                    StockMovement.objects.create(
                        tenant=tenant,
                        product=product,
                        movement_type='purchase',
                        quantity=quantity_diff,
                        previous_quantity=product.quantity,
                        new_quantity=new_quantity,
                        unit_price=product.purchase_price,
                        total_price=quantity_diff * product.purchase_price,
                        reference='Manual adjustment',
                        notes='Stock increased via product edit',
                        created_by=request.user
                    )
                else:
                    quantity_diff = product.quantity - new_quantity
                    StockMovement.objects.create(
                        tenant=tenant,
                        product=product,
                        movement_type='adjustment',
                        quantity=quantity_diff,
                        previous_quantity=product.quantity,
                        new_quantity=new_quantity,
                        unit_price=product.purchase_price,
                        total_price=quantity_diff * product.purchase_price,
                        reference='Manual adjustment',
                        notes='Stock decreased via product edit',
                        created_by=request.user
                    )
                product.quantity = new_quantity

            if request.FILES.get('image'):
                product.image = request.FILES.get('image')

            product.save()

            unit_names = request.POST.getlist('unit_names[]')
            unit_abbrs = request.POST.getlist('unit_abbrs[]')
            unit_quantities = request.POST.getlist('unit_quantities[]')
            unit_prices = request.POST.getlist('unit_prices[]')
            unit_costs = request.POST.getlist('unit_costs[]')
            default_unit_index = request.POST.get('default_unit')

            product.sale_units.all().delete()

            smallest_quantity = Decimal('999999')
            smallest_unit_name = ''
            smallest_abbr = ''

            for i in range(len(unit_names)):
                if not unit_names[i] or not unit_abbrs[i] or not unit_quantities[i] or not unit_prices[i]:
                    continue

                qty_per_unit = Decimal(unit_quantities[i] or 0)

                if qty_per_unit < smallest_quantity:
                    smallest_quantity = qty_per_unit
                    smallest_unit_name = unit_names[i].strip()
                    smallest_abbr = unit_abbrs[i].strip()

                is_default = (default_unit_index == str(i))

                SaleUnit.objects.create(
                    tenant=tenant,
                    product=product,
                    name=unit_names[i].strip(),
                    abbreviation=unit_abbrs[i].strip(),
                    quantity_per_unit=qty_per_unit,
                    selling_price=Decimal(unit_prices[i] or 0),
                    purchase_price=Decimal(unit_costs[i] if i < len(unit_costs) else 0),
                    is_default=is_default,
                    is_active=True
                )

            if smallest_unit_name:
                base_unit, created = Unit.objects.get_or_create(
                    tenant=tenant,
                    name=smallest_unit_name,
                    defaults={
                        'abbreviation': smallest_abbr,
                        'created_by': request.user
                    }
                )
                product.unit = base_unit
                product.save()

            # Check for alerts after update
            check_product_alerts(product)

            messages.success(request, f'Product "{product.name}" updated successfully!')
            return redirect('inventory:product_detail', product_id=product.id)

        except Exception as e:
            messages.error(request, f'Error updating product: {str(e)}')
            logger.error(f"Product update error: {str(e)}")

        return redirect('inventory:product_edit', product_id=product_id)

    categories = Category.objects.filter(tenant=tenant)
    units = Unit.objects.filter(tenant=tenant)

    context = {
        'product': product,
        'categories': categories,
        'units': units,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Edit Product - PharmaPro'
    }
    return render(request, 'inventory/product_edit.html', context)


@login_required
def product_delete_view(request, product_id):
    """Delete a product - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)

    if request.method == 'POST':
        try:
            from sales.models import SaleItem
            if SaleItem.objects.filter(product=product).exists():
                messages.error(request, f'Cannot delete "{product.name}" as it has sales records.')
                return redirect('inventory:product_detail', product_id=product_id)

            StockMovement.objects.filter(product=product, tenant=tenant).delete()
            InventoryAlert.objects.filter(product=product, tenant=tenant).delete()

            product.delete()
            messages.success(request, f'Product "{product.name}" deleted successfully!')
            return redirect('inventory:product_list')

        except Exception as e:
            messages.error(request, f'Error deleting product: {str(e)}')
            return redirect('inventory:product_detail', product_id=product_id)

    context = {
        'product': product,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Delete Product - PharmaPro'
    }
    return render(request, 'inventory/product_delete.html', context)


# ==================== STOCK MOVEMENT VIEWS ====================

@login_required
def product_stock_update_view(request, product_id):
    """Update product stock with unit support - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)

    if request.method == 'POST':
        try:
            quantity = Decimal(request.POST.get('quantity', 0) or 0)
            movement_type = request.POST.get('movement_type', 'in')
            unit_type = request.POST.get('unit_type', 'base')
            reference = request.POST.get('reference', '').strip()
            notes = request.POST.get('notes', '').strip()

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('inventory:product_stock_update', product_id=product_id)

            # Calculate base quantity
            base_quantity = quantity
            unit_name = 'base'

            if unit_type != 'base':
                # Find the sale unit
                sale_unit = product.sale_units.filter(id=unit_type).first()
                if sale_unit:
                    base_quantity = quantity * sale_unit.quantity_per_unit
                    unit_name = sale_unit.name
                else:
                    messages.error(request, 'Invalid unit selected.')
                    return redirect('inventory:product_stock_update', product_id=product_id)

            previous_quantity = product.quantity

            if movement_type == 'in':
                product.quantity += base_quantity
            else:
                if product.quantity < base_quantity:
                    messages.error(request, f'Insufficient stock. Current stock: {product.quantity} base units')
                    return redirect('inventory:product_stock_update', product_id=product_id)
                product.quantity -= base_quantity

            product.save()

            # Create stock movement record
            StockMovement.objects.create(
                tenant=tenant,
                product=product,
                movement_type='purchase' if movement_type == 'in' else 'sale',
                quantity=base_quantity,
                previous_quantity=previous_quantity,
                new_quantity=product.quantity,
                unit_price=product.purchase_price,
                total_price=base_quantity * product.purchase_price,
                reference=reference or f'{movement_type.upper()} - {product.name}',
                notes=f'{notes} - {quantity} {unit_name}(s) = {base_quantity} base units' if notes else f'{quantity} {unit_name}(s) = {base_quantity} base units',
                sale_unit_name=unit_name,
                sale_quantity=quantity,
                created_by=request.user
            )

            # Check and create alerts
            check_product_alerts(product)

            messages.success(
                request,
                f'Stock {movement_type} successful. Added {quantity} {unit_name}(s) = {base_quantity} base units. '
                f'New quantity: {product.quantity} base units'
            )
            return redirect('inventory:product_detail', product_id=product_id)

        except ValueError as e:
            messages.error(request, f'Invalid quantity: {str(e)}')
        except Exception as e:
            messages.error(request, f'Error updating stock: {str(e)}')
            logger.error(f"Stock update error: {str(e)}")

        return redirect('inventory:product_stock_update', product_id=product_id)

    context = {
        'product': product,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Update Stock - PharmaPro'
    }
    return render(request, 'inventory/product_stock_update.html', context)


# apps/inventory/views.py - Replace stock_movement_view

@login_required
def stock_movement_view(request):
    """View stock movements with advanced filtering - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    # Base queryset for all movements
    all_movements = StockMovement.objects.filter(tenant=tenant)

    # Calculate totals from ALL movements (before filters)
    total_in = all_movements.filter(
        movement_type__in=['purchase', 'return', 'add_stock']
    ).aggregate(total=Sum('quantity'))['total'] or Decimal(0)

    total_out = all_movements.filter(
        movement_type__in=['sale', 'waste', 'damaged', 'stolen', 'lost']
    ).aggregate(total=Sum('quantity'))['total'] or Decimal(0)

    # Now apply filters for the displayed list
    movements = all_movements.select_related('product', 'created_by', 'approved_by').order_by('-created_at')

    # Search filter (product name, SKU, reference)
    search_query = request.GET.get('search', '')
    if search_query:
        movements = movements.filter(
            Q(product__name__icontains=search_query) |
            Q(product__sku__icontains=search_query) |
            Q(product__barcode__icontains=search_query) |
            Q(reference__icontains=search_query) |
            Q(notes__icontains=search_query)
        )

    # Product filter
    product_filter = request.GET.get('product', '')
    if product_filter:
        movements = movements.filter(product_id=product_filter)

    # Category filter (filter products by category)
    category_filter = request.GET.get('category', '')
    if category_filter:
        movements = movements.filter(product__category_id=category_filter)

    # Movement type filter
    movement_type_filter = request.GET.get('type', '')
    if movement_type_filter:
        movements = movements.filter(movement_type=movement_type_filter)

    # Movement subtype filter (for adjustments)
    movement_subtype_filter = request.GET.get('subtype', '')
    if movement_subtype_filter:
        movements = movements.filter(movement_subtype=movement_subtype_filter)

    # Period filter
    period_filter = request.GET.get('period', '')
    today = timezone.now().date()

    if period_filter == 'today':
        movements = movements.filter(created_at__date=today)
    elif period_filter == 'yesterday':
        yesterday = today - datetime.timedelta(days=1)
        movements = movements.filter(created_at__date=yesterday)
    elif period_filter == 'this_week':
        start_of_week = today - datetime.timedelta(days=today.weekday())
        movements = movements.filter(created_at__date__gte=start_of_week)
    elif period_filter == 'last_week':
        start_of_last_week = today - datetime.timedelta(days=today.weekday() + 7)
        end_of_last_week = start_of_last_week + datetime.timedelta(days=6)
        movements = movements.filter(created_at__date__gte=start_of_last_week, created_at__date__lte=end_of_last_week)
    elif period_filter == 'this_month':
        start_of_month = today.replace(day=1)
        movements = movements.filter(created_at__date__gte=start_of_month)
    elif period_filter == 'last_month':
        first_day_current_month = today.replace(day=1)
        last_day_last_month = first_day_current_month - datetime.timedelta(days=1)
        first_day_last_month = last_day_last_month.replace(day=1)
        movements = movements.filter(created_at__date__gte=first_day_last_month, created_at__date__lte=last_day_last_month)
    elif period_filter == 'this_year':
        start_of_year = today.replace(month=1, day=1)
        movements = movements.filter(created_at__date__gte=start_of_year)
    elif period_filter == 'last_year':
        start_of_last_year = today.replace(year=today.year - 1, month=1, day=1)
        end_of_last_year = today.replace(year=today.year - 1, month=12, day=31)
        movements = movements.filter(created_at__date__gte=start_of_last_year, created_at__date__lte=end_of_last_year)
    elif period_filter == 'last_7_days':
        start_date = today - datetime.timedelta(days=7)
        movements = movements.filter(created_at__date__gte=start_date)
    elif period_filter == 'last_30_days':
        start_date = today - datetime.timedelta(days=30)
        movements = movements.filter(created_at__date__gte=start_date)
    elif period_filter == 'last_90_days':
        start_date = today - datetime.timedelta(days=90)
        movements = movements.filter(created_at__date__gte=start_date)

    # Date range filter
    date_from = request.GET.get('date_from', '')
    if date_from:
        try:
            date_from_obj = datetime.datetime.strptime(date_from, '%Y-%m-%d').date()
            movements = movements.filter(created_at__date__gte=date_from_obj)
        except ValueError:
            pass

    date_to = request.GET.get('date_to', '')
    if date_to:
        try:
            date_to_obj = datetime.datetime.strptime(date_to, '%Y-%m-%d').date()
            movements = movements.filter(created_at__date__lte=date_to_obj)
        except ValueError:
            pass

    paginator = Paginator(movements, 50)
    page_number = request.GET.get('page', 1)
    movements_page = paginator.get_page(page_number)

    # Get all products and categories for filters
    products = Product.objects.filter(tenant=tenant)
    categories = Category.objects.filter(tenant=tenant)
    
    # Get movement subtypes for filter
    movement_subtypes = StockMovement.objects.filter(tenant=tenant).values_list('movement_subtype', flat=True).distinct().exclude(movement_subtype='')

    context = {
        'movements': movements_page,
        'products': products,
        'categories': categories,
        'movement_subtypes': movement_subtypes,
        'search_query': search_query,
        'product_filter': product_filter,
        'category_filter': category_filter,
        'movement_type_filter': movement_type_filter,
        'movement_subtype_filter': movement_subtype_filter,
        'period_filter': period_filter,
        'date_from': date_from,
        'date_to': date_to,
        'total_in': total_in,
        'total_out': total_out,
        'net_movement': total_in - total_out,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Stock Movements - PharmaPro'
    }
    return render(request, 'inventory/stock_movements.html', context)


# apps/inventory/views.py - Replace stock_movement_create_view

@login_required
def stock_movement_create_view(request):
    """Create a stock movement with advanced options - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            product_id = request.POST.get('product')
            movement_type = request.POST.get('movement_type')
            quantity = Decimal(request.POST.get('quantity', 0) or 0)
            reference = request.POST.get('reference', '').strip()
            notes = request.POST.get('notes', '').strip()
            unit_type = request.POST.get('unit_type', 'base')
            movement_subtype = request.POST.get('movement_subtype', '')
            damage_reason = request.POST.get('damage_reason', '')
            value_loss = Decimal(request.POST.get('value_loss', 0) or 0)

            if not product_id:
                messages.error(request, 'Please select a product.')
                return redirect('inventory:stock_movement_create')

            product = get_object_or_404(Product, id=product_id, tenant=tenant)

            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('inventory:stock_movement_create')

            # Handle unit conversion
            base_quantity = quantity
            unit_name = 'base'
            if unit_type != 'base':
                sale_unit = product.sale_units.filter(id=unit_type).first()
                if sale_unit:
                    base_quantity = quantity * sale_unit.quantity_per_unit
                    unit_name = sale_unit.name
                else:
                    messages.error(request, 'Invalid unit selected.')
                    return redirect('inventory:stock_movement_create')

            previous_quantity = product.quantity
            
            # Determine movement direction
            is_increase = movement_type in ['purchase', 'return', 'add_stock']
            is_decrease = movement_type in ['sale', 'waste', 'damaged', 'stolen', 'lost', 'adjustment']
            
            # For adjustment, movement type determines direction
            if movement_type == 'adjustment':
                # Use the movement_subtype to determine direction
                if movement_subtype == 'increase':
                    is_increase = True
                    is_decrease = False
                elif movement_subtype == 'decrease':
                    is_increase = False
                    is_decrease = True
                else:
                    messages.error(request, 'Please specify adjustment direction.')
                    return redirect('inventory:stock_movement_create')

            # Check stock availability for decreases
            if is_decrease and product.quantity < base_quantity:
                messages.error(
                    request,
                    f'Insufficient stock. Available: {product.quantity} base units, Requested: {base_quantity}'
                )
                return redirect('inventory:stock_movement_create')

            # Update product quantity
            if is_increase:
                product.quantity += base_quantity
            else:
                product.quantity -= base_quantity

            product.save()

            # Calculate total price
            if is_increase:
                total_price = base_quantity * product.purchase_price
            else:
                total_price = base_quantity * product.selling_price
                if value_loss > 0:
                    total_price = value_loss

            # Create stock movement
            movement = StockMovement.objects.create(
                tenant=tenant,
                product=product,
                movement_type=movement_type,
                quantity=base_quantity,
                previous_quantity=previous_quantity,
                new_quantity=product.quantity,
                unit_price=product.purchase_price if is_increase else product.selling_price,
                total_price=total_price,
                reference=reference or f'Manual {movement_type.upper()}',
                notes=notes,
                created_by=request.user,
                sale_unit_name=unit_name,
                sale_quantity=quantity,
                movement_subtype=movement_subtype,
                damage_reason=damage_reason if movement_type == 'damaged' else '',
                value_loss=value_loss
            )

            # Check for alerts
            check_product_alerts(product)

            messages.success(
                request,
                f'Stock movement recorded successfully. {quantity} {unit_name}(s) = {base_quantity} base units. '
                f'New quantity: {product.quantity} base units'
            )
            return redirect('inventory:stock_movements')

        except ValueError as e:
            messages.error(request, f'Invalid quantity: {str(e)}')
        except Exception as e:
            messages.error(request, f'Error creating stock movement: {str(e)}')
            logger.error(f"Stock movement creation error: {str(e)}")

        return redirect('inventory:stock_movement_create')

    # GET request - show form
    products = Product.objects.filter(tenant=tenant).select_related('category', 'unit')
    categories = Category.objects.filter(tenant=tenant)
    
    # Get filter params for product search
    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category', '')
    
    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(barcode__icontains=search_query)
        )
    
    if category_filter:
        products = products.filter(category_id=category_filter)

    context = {
        'products': products,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Create Stock Movement - PharmaPro'
    }
    return render(request, 'inventory/stock_movement_create.html', context)


# ==================== ALERT VIEWS ====================

@login_required
def alerts_view(request):
    """View inventory alerts - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    alerts = InventoryAlert.objects.filter(
        tenant=tenant
    ).select_related('product').order_by('-created_at')

    # Filter by read status
    read_filter = request.GET.get('read', '')
    if read_filter == 'unread':
        alerts = alerts.filter(is_read=False)
    elif read_filter == 'read':
        alerts = alerts.filter(is_read=True)

    # Filter by alert type
    type_filter = request.GET.get('type', '')
    if type_filter:
        alerts = alerts.filter(alert_type=type_filter)

    # Filter by severity
    severity_filter = request.GET.get('severity', '')
    if severity_filter:
        alerts = alerts.filter(severity=severity_filter)

    paginator = Paginator(alerts, 20)
    page_number = request.GET.get('page', 1)
    alerts_page = paginator.get_page(page_number)

    context = {
        'alerts': alerts_page,
        'read_filter': read_filter,
        'type_filter': type_filter,
        'severity_filter': severity_filter,
        'unread_count': InventoryAlert.objects.filter(tenant=tenant, is_read=False).count(),
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Inventory Alerts - PharmaPro'
    }
    return render(request, 'inventory/alerts.html', context)


@login_required
def mark_alert_read_view(request, alert_id):
    """Mark a single alert as read - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    alert = get_object_or_404(InventoryAlert, id=alert_id, tenant=tenant)

    if request.method == 'POST':
        try:
            alert.is_read = True
            alert.read_at = timezone.now()
            alert.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Alert marked as read'})

            messages.success(request, 'Alert marked as read.')
            return redirect('inventory:alerts')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, f'Error marking alert as read: {str(e)}')

    return redirect('inventory:alerts')


@login_required
def mark_all_alerts_read_view(request):
    """Mark all alerts as read - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            count = InventoryAlert.objects.filter(
                tenant=tenant,
                is_read=False
            ).update(
                is_read=True,
                read_at=timezone.now()
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'count': count, 'message': f'{count} alerts marked as read'})

            messages.success(request, f'{count} alert(s) marked as read.')
            return redirect('inventory:alerts')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, f'Error marking alerts as read: {str(e)}')

    return redirect('inventory:alerts')


# apps/inventory/views.py - Add this view

@login_required
def mark_alert_resolved_view(request, alert_id):
    """Mark a single alert as resolved - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    alert = get_object_or_404(InventoryAlert, id=alert_id, tenant=tenant)

    if request.method == 'POST':
        try:
            alert.is_resolved = True
            alert.resolved_at = timezone.now()
            alert.resolved_by = request.user
            alert.is_read = True  # Also mark as read when resolved
            alert.read_at = timezone.now()
            alert.save()

            # Create a notification that alert was resolved
            from accounts.models import Notification
            Notification.create_notification(
                tenant=tenant,
                user=request.user,
                title=f'✅ Alert Resolved: {alert.get_alert_type_display()}',
                message=f'You have resolved the alert for "{alert.product.name if alert.product else "Product"}".',
                notification_type='success',
                category='inventory',
                link=f'/inventory/products/{alert.product.id}/' if alert.product else '/inventory/alerts/',
                link_text='View Product' if alert.product else 'View Alerts',
                icon='fa-check-circle'
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': True, 'message': 'Alert marked as resolved'})

            messages.success(request, 'Alert marked as resolved.')
            return redirect('inventory:alerts')
        except Exception as e:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)
            messages.error(request, f'Error marking alert as resolved: {str(e)}')

    return redirect('inventory:alerts')


# ==================== CATEGORY VIEWS ====================

@login_required
def category_list_view(request):
    """List all categories with hierarchy - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    categories = Category.objects.filter(tenant=tenant)

    search_query = request.GET.get('search', '')
    if search_query:
        categories = categories.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    parent_filter = request.GET.get('parent', '')
    if parent_filter == 'top':
        categories = categories.filter(parent__isnull=True)
    elif parent_filter:
        try:
            parent_category = Category.objects.get(id=parent_filter, tenant=tenant)
            categories = categories.filter(parent=parent_category)
        except Category.DoesNotExist:
            pass

    categories = categories.select_related('parent').prefetch_related('subcategories')
    all_categories = Category.objects.filter(tenant=tenant).order_by('name')

    total_categories = Category.objects.filter(tenant=tenant).count()
    active_categories = Category.objects.filter(tenant=tenant, is_active=True).count()
    total_subcategories = Category.objects.filter(tenant=tenant, parent__isnull=False).count()

    max_depth = 0
    for category in Category.objects.filter(tenant=tenant):
        depth = category.get_depth()
        if depth > max_depth:
            max_depth = depth

    context = {
        'categories': categories,
        'all_categories': all_categories,
        'search_query': search_query,
        'parent_filter': parent_filter,
        'total_categories': total_categories,
        'active_categories': active_categories,
        'total_subcategories': total_subcategories,
        'max_depth': max_depth,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Categories - PharmaPro'
    }
    return render(request, 'inventory/categories.html', context)


@login_required
def category_create_view(request):
    """Create a new category - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()

            if not name:
                messages.error(request, 'Category name is required.')
                return redirect('inventory:category_create')

            if Category.objects.filter(tenant=tenant, name=name).exists():
                messages.error(request, f'Category "{name}" already exists.')
                return redirect('inventory:category_create')

            Category.objects.create(
                tenant=tenant,
                name=name,
                description=description,
                created_by=request.user
            )

            messages.success(request, f'Category "{name}" created successfully!')
            return redirect('inventory:category_list')

        except Exception as e:
            messages.error(request, f'Error creating category: {str(e)}')
            logger.error(f"Category creation error: {str(e)}")

        return redirect('inventory:category_create')

    context = {
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Create Category - PharmaPro'
    }
    return render(request, 'inventory/category_create.html', context)


@login_required
def category_edit_view(request, category_id):
    """Edit a category - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    category = get_object_or_404(Category, id=category_id, tenant=tenant)

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            description = request.POST.get('description', '').strip()

            if not name:
                messages.error(request, 'Category name is required.')
                return redirect('inventory:category_edit', category_id=category_id)

            if Category.objects.filter(tenant=tenant, name=name).exclude(id=category_id).exists():
                messages.error(request, f'Category "{name}" already exists.')
                return redirect('inventory:category_edit', category_id=category_id)

            category.name = name
            category.description = description
            category.save()

            messages.success(request, f'Category "{category.name}" updated successfully!')
            return redirect('inventory:category_list')

        except Exception as e:
            messages.error(request, f'Error updating category: {str(e)}')
            logger.error(f"Category update error: {str(e)}")

        return redirect('inventory:category_edit', category_id=category_id)

    context = {
        'category': category,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Edit Category - PharmaPro'
    }
    return render(request, 'inventory/category_edit.html', context)


@login_required
def category_delete_view(request, category_id):
    """Delete a category - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    category = get_object_or_404(Category, id=category_id, tenant=tenant)

    if request.method == 'POST':
        try:
            if Product.objects.filter(category=category).exists():
                messages.error(
                    request,
                    f'Cannot delete category "{category.name}" as it has products assigned to it.'
                )
                return redirect('inventory:category_list')

            category_name = category.name
            category.delete()
            messages.success(request, f'Category "{category_name}" deleted successfully!')
            return redirect('inventory:category_list')

        except Exception as e:
            messages.error(request, f'Error deleting category: {str(e)}')
            logger.error(f"Category deletion error: {str(e)}")

        return redirect('inventory:category_list')

    context = {
        'category': category,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Delete Category - PharmaPro'
    }
    return render(request, 'inventory/category_delete.html', context)


# ==================== UNIT VIEWS ====================

@login_required
def unit_list_view(request):
    """List all units - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    units = Unit.objects.filter(tenant=tenant).annotate(
        product_count=Count('products')
    ).order_by('name')

    search_query = request.GET.get('search', '')
    if search_query:
        units = units.filter(name__icontains=search_query)

    paginator = Paginator(units, 20)
    page_number = request.GET.get('page', 1)
    units_page = paginator.get_page(page_number)

    context = {
        'units': units_page,
        'search_query': search_query,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Units - PharmaPro'
    }
    return render(request, 'inventory/units.html', context)


@login_required
def unit_create_view(request):
    """Create a new unit - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            abbreviation = request.POST.get('abbreviation', '').strip()

            if not name:
                messages.error(request, 'Unit name is required.')
                return redirect('inventory:unit_create')

            if not abbreviation:
                messages.error(request, 'Unit abbreviation is required.')
                return redirect('inventory:unit_create')

            if Unit.objects.filter(tenant=tenant, name=name).exists():
                messages.error(request, f'Unit "{name}" already exists.')
                return redirect('inventory:unit_create')

            Unit.objects.create(
                tenant=tenant,
                name=name,
                abbreviation=abbreviation,
                created_by=request.user
            )

            messages.success(request, f'Unit "{name}" created successfully!')
            return redirect('inventory:unit_list')

        except Exception as e:
            messages.error(request, f'Error creating unit: {str(e)}')
            logger.error(f"Unit creation error: {str(e)}")

        return redirect('inventory:unit_create')

    context = {
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Create Unit - PharmaPro'
    }
    return render(request, 'inventory/unit_create.html', context)


@login_required
def unit_edit_view(request, unit_id):
    """Edit a unit - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    unit = get_object_or_404(Unit, id=unit_id, tenant=tenant)

    if request.method == 'POST':
        try:
            name = request.POST.get('name', '').strip()
            abbreviation = request.POST.get('abbreviation', '').strip()

            if not name:
                messages.error(request, 'Unit name is required.')
                return redirect('inventory:unit_edit', unit_id=unit_id)

            if not abbreviation:
                messages.error(request, 'Unit abbreviation is required.')
                return redirect('inventory:unit_edit', unit_id=unit_id)

            if Unit.objects.filter(tenant=tenant, name=name).exclude(id=unit_id).exists():
                messages.error(request, f'Unit "{name}" already exists.')
                return redirect('inventory:unit_edit', unit_id=unit_id)

            unit.name = name
            unit.abbreviation = abbreviation
            unit.save()

            messages.success(request, f'Unit "{unit.name}" updated successfully!')
            return redirect('inventory:unit_list')

        except Exception as e:
            messages.error(request, f'Error updating unit: {str(e)}')
            logger.error(f"Unit update error: {str(e)}")

        return redirect('inventory:unit_edit', unit_id=unit_id)

    context = {
        'unit': unit,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Edit Unit - PharmaPro'
    }
    return render(request, 'inventory/unit_edit.html', context)


@login_required
def unit_delete_view(request, unit_id):
    """Delete a unit - only admins and managers"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    unit = get_object_or_404(Unit, id=unit_id, tenant=tenant)

    if request.method == 'POST':
        try:
            if Product.objects.filter(unit=unit).exists():
                messages.error(
                    request,
                    f'Cannot delete unit "{unit.name}" as it has products using it.'
                )
                return redirect('inventory:unit_list')

            unit_name = unit.name
            unit.delete()
            messages.success(request, f'Unit "{unit_name}" deleted successfully!')
            return redirect('inventory:unit_list')

        except Exception as e:
            messages.error(request, f'Error deleting unit: {str(e)}')
            logger.error(f"Unit deletion error: {str(e)}")

        return redirect('inventory:unit_list')

    context = {
        'unit': unit,
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Delete Unit - PharmaPro'
    }
    return render(request, 'inventory/unit_delete.html', context)


# ==================== API ENDPOINT ====================

@login_required
def product_sale_units_api(request, product_id):
    """API endpoint to get sale units for a product - viewable by all authenticated users"""
    if not user_can_view_inventory(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)

    units = product.sale_units.filter(is_active=True).values(
        'id', 'name', 'abbreviation', 'quantity_per_unit',
        'selling_price', 'purchase_price', 'is_default'
    )

    return JsonResponse({
        'units': list(units)
    })


from django.http import JsonResponse
from django.db.models import Q

@login_required
def product_search_api(request):
    """API endpoint for product search with category filter"""
    if not user_can_view_inventory(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    tenant = request.user.tenant
    search_term = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '')
    
    products = Product.objects.filter(tenant=tenant).select_related('category', 'unit')
    
    if search_term:
        products = products.filter(
            Q(name__icontains=search_term) |
            Q(sku__icontains=search_term) |
            Q(barcode__icontains=search_term)
        )
    
    if category_id:
        products = products.filter(category_id=category_id)
    
    products = products[:20]  # Limit results
    
    data = {
        'products': [
            {
                'id': str(p.id),
                'name': p.name,
                'sku': p.sku,
                'quantity': float(p.quantity),
                'category_name': p.category.name if p.category else None,
                'unit_name': p.unit.name if p.unit else None,
            }
            for p in products
        ]
    }
    
    return JsonResponse(data)


# apps/inventory/views.py - Add these functions

from django.utils import timezone
import datetime

# ==================== EXPIRY MANAGEMENT FUNCTIONS ====================

def check_expired_products():
    """Check for expired products and create alerts"""
    today = timezone.now().date()
    
    expired_products = Product.objects.filter(
        expiry_date__lt=today,
        quantity__gt=0,
        status__in=['active', 'out_of_stock']
    )
    
    for product in expired_products:
        alert, created = InventoryAlert.objects.get_or_create(
            tenant=product.tenant,
            product=product,
            alert_type='expired',
            is_resolved=False,
            defaults={
                'severity': 'critical',
                'message': f'Product "{product.name}" has expired on {product.expiry_date}. Current stock: {product.quantity} units. Please decommission immediately.',
                'is_read': False
            }
        )
        
        if created:
            send_expired_notification(product)
        
        if product.status != 'expired':
            product.status = 'expired'
            product.save(update_fields=['status'])


def send_expired_notification(product):
    """Send notification for expired products"""
    tenant = product.tenant
    recipients = User.objects.filter(
        tenant=tenant,
        role__in=['admin', 'manager', 'supervisor'],
        is_active=True
    )
    
    title = f'⚠️ EXPIRED PRODUCT ALERT: {product.name}'
    message = f'Product "{product.name}" has expired on {product.expiry_date}. Current stock: {product.quantity} units. Please decommission immediately.'
    
    for user in recipients:
        Notification.create_notification(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            notification_type='error',
            category='inventory',
            link=f'/inventory/products/{product.id}/',
            link_text='View Product',
            icon='fa-skull'
        )
    
    Notification.create_global_notification(
        tenant=tenant,
        title=f'🚨 EXPIRED PRODUCT: {product.name}',
        message=f'{product.name} expired on {product.expiry_date}. Stock: {product.quantity} units. Action required!',
        notification_type='error',
        category='inventory',
        link=f'/inventory/products/{product.id}/',
        link_text='View Product',
        icon='fa-skull'
    )

# apps/inventory/views.py - Update expired_products_view and decommissioned_products_view

@login_required
def expired_products_view(request):
    """View all expired products"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    tenant = request.user.tenant
    today = timezone.now().date()
    
    expired_products = Product.objects.filter(
        tenant=tenant,
        expiry_date__lt=today,
        quantity__gt=0
    ).select_related('category', 'unit')
    
    search_query = request.GET.get('search', '')
    if search_query:
        expired_products = expired_products.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(batch_number__icontains=search_query)
        )
    
    category_filter = request.GET.get('category', '')
    if category_filter:
        expired_products = expired_products.filter(category_id=category_filter)
    
    total_value = expired_products.aggregate(
        total=Sum(F('quantity') * F('purchase_price'))
    )['total'] or 0
    
    paginator = Paginator(expired_products, 20)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)
    
    # Add calculated value to each product
    for product in products_page:
        product.total_value = product.quantity * product.purchase_price
    
    categories = Category.objects.filter(tenant=tenant)
    
    context = {
        'products': products_page,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'total_value': total_value,
        'total_products': expired_products.count(),
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Expired Products - PharmaPro'
    }
    return render(request, 'inventory/expired_products.html', context)


@login_required
def decommissioned_products_view(request):
    """View all decommissioned products"""
    if not user_can_view_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    tenant = request.user.tenant
    
    decommissioned_products = Product.objects.filter(
        tenant=tenant,
        status='decommissioned'
    ).select_related('category', 'unit')
    
    search_query = request.GET.get('search', '')
    if search_query:
        decommissioned_products = decommissioned_products.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(batch_number__icontains=search_query)
        )
    
    category_filter = request.GET.get('category', '')
    if category_filter:
        decommissioned_products = decommissioned_products.filter(category_id=category_filter)
    
    paginator = Paginator(decommissioned_products, 20)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)
    
    # Add calculated value to each product
    for product in products_page:
        product.total_value = product.quantity * product.purchase_price
    
    categories = Category.objects.filter(tenant=tenant)
    
    context = {
        'products': products_page,
        'categories': categories,
        'search_query': search_query,
        'category_filter': category_filter,
        'total_products': decommissioned_products.count(),
        'can_manage': user_can_manage_inventory(request.user),
        'title': 'Decommissioned Products - PharmaPro'
    }
    return render(request, 'inventory/decommissioned_products.html', context)

@login_required
def decommission_expired_view(request, product_id):
    """Decommission expired products"""
    if not user_can_manage_inventory(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    tenant = request.user.tenant
    product = get_object_or_404(Product, id=product_id, tenant=tenant)
    
    if request.method == 'POST':
        try:
            quantity = Decimal(request.POST.get('quantity', 0) or 0)
            notes = request.POST.get('notes', '').strip()
            decommission_type = request.POST.get('decommission_type', 'waste')
            
            if quantity <= 0:
                messages.error(request, 'Quantity must be greater than 0.')
                return redirect('inventory:decommission_expired', product_id=product_id)
            
            if quantity > product.quantity:
                messages.error(request, f'Cannot decommission more than available stock. Available: {product.quantity}')
                return redirect('inventory:decommission_expired', product_id=product_id)
            
            previous_quantity = product.quantity
            product.quantity -= quantity
            product.save()
            
            # Create stock movement for decommission
            StockMovement.objects.create(
                tenant=tenant,
                product=product,
                movement_type='decommissioned',
                quantity=quantity,
                previous_quantity=previous_quantity,
                new_quantity=product.quantity,
                unit_price=product.purchase_price,
                total_price=quantity * product.purchase_price,
                reference=f'DECOMMISSION-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                notes=f'Decommissioned expired product. {notes}',
                created_by=request.user,
                value_loss=quantity * product.purchase_price,
                decommission_date=timezone.now()
            )
            
            # Mark alert as resolved
            InventoryAlert.objects.filter(
                tenant=tenant,
                product=product,
                alert_type='expired',
                is_resolved=False
            ).update(
                is_resolved=True,
                resolved_at=timezone.now(),
                resolved_by=request.user
            )
            
            # Update product status
            if product.quantity == 0:
                product.status = 'decommissioned'
                product.save(update_fields=['status'])
            else:
                # Still has some stock, just mark as expired if not already
                if product.status != 'expired':
                    product.status = 'expired'
                    product.save(update_fields=['status'])
            
            messages.success(
                request,
                f'Successfully decommissioned {quantity} units of "{product.name}".'
            )
            
            if product.quantity == 0:
                messages.info(request, f'All stock of "{product.name}" has been decommissioned.')
            
            return redirect('inventory:expired_products')
            
        except Exception as e:
            messages.error(request, f'Error decommissioning product: {str(e)}')
            logger.error(f"Decommission error: {str(e)}")
        
        return redirect('inventory:decommission_expired', product_id=product_id)
    
    context = {
        'product': product,
        'can_manage': user_can_manage_inventory(request.user),
        'title': f'Decommission {product.name} - PharmaPro'
    }
    return render(request, 'inventory/decommission_expired.html', context)


@login_required
def get_expired_products_api(request):
    """API endpoint to get expired products"""
    if not user_can_view_inventory(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    tenant = request.user.tenant
    today = timezone.now().date()
    
    expired_products = Product.objects.filter(
        tenant=tenant,
        expiry_date__lt=today,
        quantity__gt=0
    ).select_related('category', 'unit')
    
    data = {
        'products': [
            {
                'id': str(p.id),
                'name': p.name,
                'sku': p.sku,
                'quantity': float(p.quantity),
                'unit_name': p.unit.name if p.unit else None,
                'category_name': p.category.name if p.category else None,
                'expiry_date': p.expiry_date.strftime('%Y-%m-%d') if p.expiry_date else None,
                'purchase_price': float(p.purchase_price),
            }
            for p in expired_products
        ],
        'count': expired_products.count()
    }
    
    return JsonResponse(data)