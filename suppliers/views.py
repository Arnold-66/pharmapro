# apps/suppliers/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count
from django.utils import timezone
from decimal import Decimal
import uuid
import logging
from django.urls import reverse
from accounts.utils import create_supplier_approval_notification, create_po_approval_notification


from .models import (
    Supplier, SupplierContact, SupplierProduct,
    PurchaseOrder, PurchaseOrderItem, SupplierPayment
)
from inventory.models import Product, Category

logger = logging.getLogger(__name__)


def user_can_manage_suppliers(user):
    """Check if user can manage suppliers - Manager, Admin, Superuser"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'supervisor'])


def user_can_approve_purchase_orders(user):
    """Check if user can approve purchase orders - Only Manager, Admin, Superuser"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager'])


def user_can_view_purchase_orders(user):
    """Check if user can view purchase orders - Staff, Manager, Admin, Superuser"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'supervisor',])



# apps/suppliers/utils.py
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from accounts.models import Notification, User
import logging

logger = logging.getLogger(__name__)


def create_po_notification(purchase_order, action, actor=None):
    """
    Create notifications and send emails for PO actions

    Args:
        purchase_order: PurchaseOrder instance
        action: 'submitted', 'approved', 'rejected', 'ordered', 'received'
        actor: User who performed the action (optional)
    """
    from .models import PurchaseOrder

    tenant = purchase_order.tenant
    po_number = purchase_order.po_number
    supplier_name = purchase_order.supplier.name

    # Determine notification details based on action
    notification_configs = {
        'submitted': {
            'title': f'PO {po_number} Submitted for Approval',
            'message': f'Purchase Order {po_number} for {supplier_name} has been submitted for approval by {purchase_order.created_by.get_full_name()}. Total: UGX {purchase_order.total_amount:,.2f}',
            'type': 'warning',
            'category': 'purchase_order',
            'icon': 'fa-file-invoice',
            'email_subject': f'PO {po_number} Needs Your Approval',
            'recipient_roles': ['admin', 'manager']  # Who should receive this
        },
        'approved': {
            'title': f'PO {po_number} Approved',
            'message': f'Purchase Order {po_number} for {supplier_name} has been approved by {actor.get_full_name() if actor else "Manager"}.',
            'type': 'success',
            'category': 'purchase_order',
            'icon': 'fa-check-circle',
            'email_subject': f'PO {po_number} Has Been Approved',
            'recipient_roles': ['staff', 'supervisor']  # Notify creator and staff
        },
        'rejected': {
            'title': f'PO {po_number} Rejected',
            'message': f'Purchase Order {po_number} for {supplier_name} has been rejected by {actor.get_full_name() if actor else "Manager"}. Please review and resubmit.',
            'type': 'error',
            'category': 'purchase_order',
            'icon': 'fa-times-circle',
            'email_subject': f'PO {po_number} Has Been Rejected',
            'recipient_roles': ['staff', 'supervisor']
        },
        'ordered': {
            'title': f'PO {po_number} Ordered',
            'message': f'Purchase Order {po_number} for {supplier_name} has been placed. Supplier has been notified.',
            'type': 'info',
            'category': 'purchase_order',
            'icon': 'fa-truck',
            'email_subject': f'PO {po_number} Has Been Placed',
            'recipient_roles': ['admin', 'manager', 'staff']
        },
        'received': {
            'title': f'PO {po_number} Received',
            'message': f'Purchase Order {po_number} for {supplier_name} has been marked as received. Check inventory for updates.',
            'type': 'success',
            'category': 'purchase_order',
            'icon': 'fa-check-double',
            'email_subject': f'PO {po_number} Has Been Received',
            'recipient_roles': ['admin', 'manager', 'staff']
        }
    }

    config = notification_configs.get(action)
    if not config:
        logger.warning(f"Unknown PO action: {action}")
        return

    # Get link to PO
    link = f'/suppliers/purchase-orders/{purchase_order.id}/'
    link_text = 'View Purchase Order'

    # Determine recipients
    recipients = get_recipients_for_role(tenant, config['recipient_roles'])

    # Also add the creator if they're not already included and it's not 'submitted'
    if action != 'submitted' and purchase_order.created_by:
        if purchase_order.created_by not in recipients and purchase_order.created_by.is_active:
            recipients.append(purchase_order.created_by)

    # Add the actor if they're not already included
    if actor and actor not in recipients and actor.is_active:
        recipients.append(actor)

    # Create notifications
    notifications_created = []
    for user in recipients:
        # Skip if user is not active
        if not user.is_active:
            continue

        notification = Notification.objects.create(
            tenant=tenant,
            user=user,
            title=config['title'],
            message=config['message'],
            notification_type=config['type'],
            category=config['category'],
            icon=config['icon'],
            link=link,
            link_text=link_text,
            is_read=False
        )
        notifications_created.append(notification)

    # Send emails
    if notifications_created and settings.EMAIL_BACKEND != 'django.core.mail.backends.console.EmailBackend':
        send_po_email_notification(purchase_order, config, recipients, actor)

    logger.info(f"PO notification created for {po_number}: action={action}, recipients={len(notifications_created)}")
    return notifications_created


def create_supplier_approval_notification(supplier, action, actor=None):
    """
    Create notifications and send emails for supplier approval actions

    Args:
        supplier: Supplier instance
        action: 'submitted', 'approved', 'rejected'
        actor: User who performed the action (optional)
    """
    tenant = supplier.tenant
    supplier_name = supplier.name

    notification_configs = {
        'submitted': {
            'title': f'New Supplier Registration: {supplier_name}',
            'message': f'Supplier "{supplier_name}" has been registered and needs approval. Contact: {supplier.contact_person or "N/A"}, Email: {supplier.email or "N/A"}',
            'type': 'warning',
            'category': 'supplier',
            'icon': 'fa-user-plus',
            'email_subject': f'New Supplier Needs Approval: {supplier_name}',
            'recipient_roles': ['admin', 'manager']
        },
        'approved': {
            'title': f'Supplier {supplier_name} Approved',
            'message': f'Supplier "{supplier_name}" has been approved by {actor.get_full_name() if actor else "Manager"}. You can now create purchase orders with this supplier.',
            'type': 'success',
            'category': 'supplier',
            'icon': 'fa-check-circle',
            'email_subject': f'Supplier {supplier_name} Has Been Approved',
            'recipient_roles': ['staff', 'supervisor']
        },
        'rejected': {
            'title': f'Supplier {supplier_name} Rejected',
            'message': f'Supplier "{supplier_name}" has been rejected by {actor.get_full_name() if actor else "Manager"}. Please contact the supplier for more information.',
            'type': 'error',
            'category': 'supplier',
            'icon': 'fa-times-circle',
            'email_subject': f'Supplier {supplier_name} Has Been Rejected',
            'recipient_roles': ['staff', 'supervisor']
        }
    }

    config = notification_configs.get(action)
    if not config:
        logger.warning(f"Unknown supplier action: {action}")
        return

    # Get link to supplier
    link = f'/suppliers/suppliers/{supplier.id}/'
    link_text = 'View Supplier'

    # Determine recipients
    recipients = get_recipients_for_role(tenant, config['recipient_roles'])

    # Also add the creator if they're not already included and action is not 'submitted'
    if action != 'submitted' and supplier.created_by:
        if supplier.created_by not in recipients and supplier.created_by.is_active:
            recipients.append(supplier.created_by)

    # Add the actor if they're not already included
    if actor and actor not in recipients and actor.is_active:
        recipients.append(actor)

    # Create notifications
    notifications_created = []
    for user in recipients:
        if not user.is_active:
            continue

        notification = Notification.objects.create(
            tenant=tenant,
            user=user,
            title=config['title'],
            message=config['message'],
            notification_type=config['type'],
            category=config['category'],
            icon=config['icon'],
            link=link,
            link_text=link_text,
            is_read=False
        )
        notifications_created.append(notification)

    # Send emails
    if notifications_created and settings.EMAIL_BACKEND != 'django.core.mail.backends.console.EmailBackend':
        send_supplier_email_notification(supplier, config, recipients, actor)

    logger.info(f"Supplier approval notification created for {supplier_name}: action={action}, recipients={len(notifications_created)}")
    return notifications_created


def get_recipients_for_role(tenant, roles):
    """Get active users for a tenant with specific roles"""
    from accounts.models import User

    users = User.objects.filter(
        tenant=tenant,
        is_active=True,
        role__in=roles
    )
    return list(users)


def send_po_email_notification(purchase_order, config, recipients, actor=None):
    """Send email notification for PO actions"""
    try:
        for user in recipients:
            if not user.email:
                continue

            context = {
                'user': user,
                'purchase_order': purchase_order,
                'po_number': purchase_order.po_number,
                'supplier_name': purchase_order.supplier.name,
                'total_amount': purchase_order.total_amount,
                'action': config['title'],
                'message': config['message'],
                'actor': actor,
                'link': f"{settings.SITE_URL}/suppliers/purchase-orders/{purchase_order.id}/",
                'site_name': 'PharmaPro',
            }

            html_message = render_to_string('emails/po_notification.html', context)
            plain_message = strip_tags(html_message)

            send_mail(
                subject=config['email_subject'],
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True,
            )

    except Exception as e:
        logger.error(f"Error sending PO email notification: {str(e)}")


def send_supplier_email_notification(supplier, config, recipients, actor=None):
    """Send email notification for supplier approval actions"""
    try:
        for user in recipients:
            if not user.email:
                continue

            context = {
                'user': user,
                'supplier': supplier,
                'supplier_name': supplier.name,
                'action': config['title'],
                'message': config['message'],
                'actor': actor,
                'link': f"{settings.SITE_URL}/suppliers/suppliers/{supplier.id}/",
                'site_name': 'PharmaPro',
            }

            html_message = render_to_string('emails/supplier_notification.html', context)
            plain_message = strip_tags(html_message)

            send_mail(
                subject=config['email_subject'],
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True,
            )

    except Exception as e:
        logger.error(f"Error sending supplier email notification: {str(e)}")



# ==================== SUPPLIER MANAGEMENT ====================

@login_required
def supplier_list_view(request):
    """List all suppliers - Staff, Manager, Admin, Superuser"""
    if not user_can_manage_suppliers(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    suppliers = Supplier.objects.filter(tenant=tenant)

    # Calculate statistics BEFORE filtering
    total_suppliers = suppliers.count()
    active_suppliers = suppliers.filter(status='active').count()
    approved_suppliers = suppliers.filter(is_approved=True).count()
    pending_suppliers = suppliers.filter(is_approved=False).count()

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        suppliers = suppliers.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(contact_person__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        suppliers = suppliers.filter(status=status_filter)

    # Filter by supplier type
    type_filter = request.GET.get('type', '')
    if type_filter:
        suppliers = suppliers.filter(supplier_type=type_filter)

    # Filter by approval
    approved_filter = request.GET.get('approved', '')
    if approved_filter == 'approved':
        suppliers = suppliers.filter(is_approved=True)
    elif approved_filter == 'pending':
        suppliers = suppliers.filter(is_approved=False)

    suppliers = suppliers.order_by('name')

    paginator = Paginator(suppliers, 20)
    page_number = request.GET.get('page', 1)
    suppliers_page = paginator.get_page(page_number)

    context = {
        'suppliers': suppliers_page,
        'total_suppliers': total_suppliers,
        'active_suppliers': active_suppliers,
        'approved_suppliers': approved_suppliers,
        'pending_suppliers': pending_suppliers,
        'search_query': search_query,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'approved_filter': approved_filter,
        'title': 'Suppliers - PharmaPro'
    }
    return render(request, 'suppliers/list.html', context)


# apps/suppliers/views.py - Update supplier_create_view

@login_required
def supplier_create_view(request):
    """Create a new supplier - Staff, Manager, Admin, Superuser"""
    if not user_can_manage_suppliers(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            # Generate unique code
            code = request.POST.get('code', '').strip()
            if not code:
                name = request.POST.get('name', '').strip()
                code = name[:3].upper() + str(uuid.uuid4().hex[:4].upper())

            # Check if code exists
            if Supplier.objects.filter(tenant=tenant, code=code).exists():
                messages.error(request, f'Supplier code "{code}" already exists.')
                return redirect('suppliers:supplier_create')

            supplier = Supplier.objects.create(
                tenant=tenant,
                name=request.POST.get('name', '').strip(),
                code=code,
                supplier_type=request.POST.get('supplier_type', 'other'),
                contact_person=request.POST.get('contact_person', '').strip(),
                email=request.POST.get('email', '').strip(),
                phone=request.POST.get('phone', '').strip(),
                alternative_phone=request.POST.get('alternative_phone', '').strip(),
                address=request.POST.get('address', '').strip(),
                city=request.POST.get('city', '').strip(),
                state=request.POST.get('state', '').strip(),
                country=request.POST.get('country', 'Uganda').strip(),
                postal_code=request.POST.get('postal_code', '').strip(),
                tax_id=request.POST.get('tax_id', '').strip(),
                registration_number=request.POST.get('registration_number', '').strip(),
                payment_terms=request.POST.get('payment_terms', 'Net 30'),
                credit_limit=Decimal(request.POST.get('credit_limit', 0) or 0),
                lead_time_days=int(request.POST.get('lead_time_days', 0) or 0),
                notes=request.POST.get('notes', '').strip(),
                created_by=request.user,
                # New suppliers need approval by default
                is_approved=False,
                is_verified=False
            )

            # Add categories if any
            category_ids = request.POST.getlist('categories')
            if category_ids:
                supplier.categories.add(*category_ids)

            # ===== SEND APPROVAL NOTIFICATION =====
            from accounts.utils import create_supplier_approval_notification
            create_supplier_approval_notification(supplier, 'submitted', request.user)

            # ===== SEND CONFIRMATION TO CREATOR =====
            Notification.create_notification(
                tenant=tenant,
                user=request.user,
                title=f'Supplier "{supplier.name}" Created',
                message=f'Your supplier "{supplier.name}" has been created and submitted for approval. You will be notified when it is approved.',
                notification_type='info',
                category='supplier',
                link=f'/suppliers/suppliers/{supplier.id}/',
                link_text='View Supplier',
                icon='fa-user-check'
            )

            messages.success(
                request,
                f'Supplier "{supplier.name}" created successfully! It has been submitted for approval.'
            )
            return redirect('suppliers:supplier_detail', supplier_id=supplier.id)

        except Exception as e:
            messages.error(request, f'Error creating supplier: {str(e)}')
            logger.error(f"Supplier creation error: {str(e)}")
            return redirect('suppliers:supplier_create')

    categories = Category.objects.filter(tenant=tenant, is_active=True)

    context = {
        'categories': categories,
        'title': 'Create Supplier - PharmaPro'
    }
    return render(request, 'suppliers/create.html', context)



@login_required
def supplier_detail_view(request, supplier_id):
    """View supplier details - Staff, Manager, Admin, Superuser"""
    if not user_can_manage_suppliers(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)
    contacts = supplier.contacts.all()

    # Get products for this supplier
    products = supplier.supplier_products.select_related('product').filter(is_active=True)

    purchase_orders = supplier.purchase_orders.order_by('-created_at')[:10]

    context = {
        'supplier': supplier,
        'contacts': contacts,
        'products': products,
        'purchase_orders': purchase_orders,
        'title': f'{supplier.name} - PharmaPro'
    }
    return render(request, 'suppliers/detail.html', context)


@login_required
def supplier_edit_view(request, supplier_id):
    """Edit a supplier - Manager, Admin, Superuser only (not Staff)"""
    if not user_can_approve_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            supplier.name = request.POST.get('name', supplier.name).strip()
            supplier.supplier_type = request.POST.get('supplier_type', supplier.supplier_type)
            supplier.contact_person = request.POST.get('contact_person', supplier.contact_person).strip()
            supplier.email = request.POST.get('email', supplier.email).strip()
            supplier.phone = request.POST.get('phone', supplier.phone).strip()
            supplier.alternative_phone = request.POST.get('alternative_phone', supplier.alternative_phone).strip()
            supplier.address = request.POST.get('address', supplier.address).strip()
            supplier.city = request.POST.get('city', supplier.city).strip()
            supplier.state = request.POST.get('state', supplier.state).strip()
            supplier.country = request.POST.get('country', supplier.country).strip()
            supplier.postal_code = request.POST.get('postal_code', supplier.postal_code).strip()
            supplier.tax_id = request.POST.get('tax_id', supplier.tax_id).strip()
            supplier.registration_number = request.POST.get('registration_number', supplier.registration_number).strip()
            supplier.payment_terms = request.POST.get('payment_terms', supplier.payment_terms)
            supplier.credit_limit = Decimal(request.POST.get('credit_limit', supplier.credit_limit) or 0)
            supplier.lead_time_days = int(request.POST.get('lead_time_days', supplier.lead_time_days) or 0)
            supplier.status = request.POST.get('status', supplier.status)
            supplier.is_approved = request.POST.get('is_approved') == 'on'
            supplier.notes = request.POST.get('notes', supplier.notes).strip()
            supplier.internal_notes = request.POST.get('internal_notes', supplier.internal_notes).strip()
            supplier.quality_rating = int(request.POST.get('quality_rating', 0) or 0)
            supplier.reliability_score = int(request.POST.get('reliability_score', 0) or 0)
            supplier.save()

            # Update categories
            supplier.categories.clear()
            category_ids = request.POST.getlist('categories')
            if category_ids:
                supplier.categories.add(*category_ids)

            messages.success(request, f'Supplier "{supplier.name}" updated successfully!')
            return redirect('suppliers:supplier_detail', supplier_id=supplier.id)

        except Exception as e:
            messages.error(request, f'Error updating supplier: {str(e)}')
            logger.error(f"Supplier update error: {str(e)}")
            return redirect('suppliers:supplier_edit', supplier_id=supplier_id)

    categories = Category.objects.filter(tenant=tenant, is_active=True)

    context = {
        'supplier': supplier,
        'categories': categories,
        'title': f'Edit Supplier - {supplier.name}'
    }
    return render(request, 'suppliers/edit.html', context)


@login_required
def supplier_delete_view(request, supplier_id):
    """Delete a supplier - Manager, Admin, Superuser only (not Staff)"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            # Check if supplier has purchase orders
            if supplier.purchase_orders.exists():
                messages.error(
                    request,
                    f'Cannot delete "{supplier.name}" as it has purchase orders associated.'
                )
                return redirect('suppliers:supplier_detail', supplier_id=supplier_id)

            supplier_name = supplier.name
            supplier.delete()
            messages.success(request, f'Supplier "{supplier_name}" deleted successfully!')
            return redirect('suppliers:supplier_list')

        except Exception as e:
            messages.error(request, f'Error deleting supplier: {str(e)}')
            return redirect('suppliers:supplier_detail', supplier_id=supplier_id)

    context = {
        'supplier': supplier,
        'title': f'Delete Supplier - {supplier.name}'
    }
    return render(request, 'suppliers/delete.html', context)


@login_required
def supplier_toggle_status_view(request, supplier_id):
    """Toggle supplier status - Manager, Admin, Superuser only (not Staff)"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            status_map = {
                'active': 'inactive',
                'inactive': 'active',
                'suspended': 'active',
                'blacklisted': 'suspended',
            }
            supplier.status = status_map.get(supplier.status, 'active')
            supplier.save()

            return JsonResponse({
                'success': True,
                'status': supplier.status,
                'message': f'Supplier status updated to {supplier.get_status_display()}'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)



@login_required
def supplier_product_add_view(request, supplier_id):
    """Add a product to a supplier - Staff, Manager, Admin, Superuser"""
    if not user_can_manage_suppliers(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            product_id = request.POST.get('product_id')
            if not product_id:
                product_id = request.POST.get('product')

            if not product_id:
                return JsonResponse({
                    'success': False,
                    'error': 'Product ID is required'
                }, status=400)

            try:
                product = Product.objects.get(id=product_id, tenant=tenant)
            except Product.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Product not found'
                }, status=404)

            # Check if already exists
            if SupplierProduct.objects.filter(supplier=supplier, product=product).exists():
                return JsonResponse({
                    'success': False,
                    'error': f'Product "{product.name}" is already added to this supplier'
                }, status=400)

            # Get cost price
            cost_price = request.POST.get('cost_price', '0')
            try:
                cost_price = Decimal(str(cost_price).replace(',', ''))
            except:
                cost_price = Decimal('0')

            # Get min order quantity
            min_order = request.POST.get('min_order_quantity', '1')
            try:
                min_order = Decimal(str(min_order).replace(',', ''))
            except:
                min_order = Decimal('1')

            # Get lead time
            lead_time = request.POST.get('lead_time_days', '7')
            try:
                lead_time = int(lead_time)
            except:
                lead_time = 7

            supplier_product = SupplierProduct.objects.create(
                tenant=tenant,
                supplier=supplier,
                product=product,
                supplier_product_code=request.POST.get('supplier_product_code', '').strip(),
                supplier_product_name=request.POST.get('supplier_product_name', product.name).strip(),
                cost_price=cost_price,
                min_order_quantity=min_order,
                lead_time_days=lead_time,
                is_preferred=request.POST.get('is_preferred') == 'on'
            )

            return JsonResponse({
                'success': True,
                'message': f'Product "{product.name}" added to supplier successfully',
                'data': {
                    'id': str(supplier_product.id),
                    'product_id': str(product.id),
                    'product_name': product.name,
                    'cost_price': float(supplier_product.cost_price),
                }
            })

        except Exception as e:
            logger.error(f"Error adding product to supplier: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def supplier_product_remove_view(request, supplier_product_id):
    """Remove a product from a supplier - Staff, Manager, Admin, Superuser"""
    if not user_can_manage_suppliers(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier_product = get_object_or_404(SupplierProduct, id=supplier_product_id, tenant=tenant)

    if request.method == 'POST':
        try:
            product_name = supplier_product.product.name
            supplier_product.delete()
            return JsonResponse({
                'success': True,
                'message': f'Product "{product_name}" removed from supplier successfully'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


# ==================== PURCHASE ORDERS ====================

@login_required
def purchase_order_list_view(request):
    """List all purchase orders - Staff, Manager, Admin, Superuser"""
    if not user_can_view_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    pos = PurchaseOrder.objects.filter(tenant=tenant)

    # Statistics
    total_pos = pos.count()
    draft_pos = pos.filter(status='draft').count()
    pending_pos = pos.filter(status='pending').count()
    approved_pos = pos.filter(status='approved').count()
    ordered_pos = pos.filter(status='ordered').count()
    received_pos = pos.filter(status='received').count()
    cancelled_pos = pos.filter(status='cancelled').count()

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        pos = pos.filter(
            Q(po_number__icontains=search_query) |
            Q(supplier__name__icontains=search_query) |
            Q(supplier__code__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        pos = pos.filter(status=status_filter)

    # Filter by supplier
    supplier_filter = request.GET.get('supplier', '')
    if supplier_filter:
        pos = pos.filter(supplier_id=supplier_filter)

    # Filter by date range
    date_from = request.GET.get('date_from', '')
    if date_from:
        pos = pos.filter(created_at__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        pos = pos.filter(created_at__date__lte=date_to)

    pos = pos.order_by('-created_at')

    paginator = Paginator(pos, 20)
    page_number = request.GET.get('page', 1)
    pos_page = paginator.get_page(page_number)

    suppliers = Supplier.objects.filter(tenant=tenant, status='active')

    context = {
        'purchase_orders': pos_page,
        'total_pos': total_pos,
        'draft_pos': draft_pos,
        'pending_pos': pending_pos,
        'approved_pos': approved_pos,
        'ordered_pos': ordered_pos,
        'received_pos': received_pos,
        'cancelled_pos': cancelled_pos,
        'search_query': search_query,
        'status_filter': status_filter,
        'supplier_filter': supplier_filter,
        'date_from': date_from,
        'date_to': date_to,
        'suppliers': suppliers,
        'title': 'Purchase Orders - PharmaPro'
    }
    return render(request, 'suppliers/purchase_orders/list.html', context)




@login_required
def purchase_order_detail_view(request, po_id):
    """View purchase order details - Staff, Manager, Admin, Superuser"""
    if not user_can_view_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    po = get_object_or_404(PurchaseOrder, id=po_id, tenant=tenant)
    items = po.items.all()

    context = {
        'po': po,
        'items': items,
        'title': f'{po.po_number} - PharmaPro'
    }
    return render(request, 'suppliers/purchase_orders/detail.html', context)


@login_required
def purchase_order_edit_view(request, po_id):
    """Edit a purchase order - Staff, Manager, Admin, Superuser (only draft/pending)"""
    if not user_can_view_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    po = get_object_or_404(PurchaseOrder, id=po_id, tenant=tenant)

    # Only allow editing if draft or pending
    if po.status not in ['draft', 'pending']:
        messages.error(request, 'This purchase order cannot be edited.')
        return redirect('suppliers:purchase_order_detail', po_id=po.id)

    if request.method == 'POST':
        try:
            supplier_id = request.POST.get('supplier')
            expected_delivery = request.POST.get('expected_delivery_date')
            notes = request.POST.get('notes', '').strip()

            if supplier_id:
                supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)
                po.supplier = supplier

            po.expected_delivery_date = expected_delivery
            po.notes = notes
            po.save()

            # Delete existing items
            po.items.all().delete()

            # Process items
            product_ids = request.POST.getlist('product_ids[]')
            quantities = request.POST.getlist('quantities[]')
            unit_prices = request.POST.getlist('unit_prices[]')

            total = 0
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i] and unit_prices[i]:
                    product = get_object_or_404(Product, id=product_ids[i], tenant=tenant)
                    quantity = Decimal(quantities[i])
                    unit_price = Decimal(unit_prices[i])
                    total_price = quantity * unit_price
                    total += total_price

                    PurchaseOrderItem.objects.create(
                        purchase_order=po,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        total_price=total_price
                    )

            # Update totals
            po.subtotal = total
            po.total_amount = total
            po.save(update_fields=['subtotal', 'total_amount'])

            messages.success(request, f'Purchase Order {po.po_number} updated successfully!')
            return redirect('suppliers:purchase_order_detail', po_id=po.id)

        except Exception as e:
            messages.error(request, f'Error updating purchase order: {str(e)}')
            logger.error(f"PO update error: {str(e)}")
            return redirect('suppliers:purchase_order_edit', po_id=po.id)

    suppliers = Supplier.objects.filter(tenant=tenant, status='active')
    products = Product.objects.filter(tenant=tenant, is_active=True)

    context = {
        'po': po,
        'items': po.items.all(),
        'suppliers': suppliers,
        'products': products,
        'title': f'Edit {po.po_number} - PharmaPro'
    }
    return render(request, 'suppliers/purchase_orders/edit.html', context)


@login_required
def purchase_order_delete_view(request, po_id):
    """Delete a purchase order - Staff, Manager, Admin, Superuser (only draft/pending)"""
    if not user_can_view_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    po = get_object_or_404(PurchaseOrder, id=po_id, tenant=tenant)

    if request.method == 'POST':
        try:
            po_number = po.po_number
            po.delete()
            return JsonResponse({
                'success': True,
                'message': f'Purchase Order {po_number} deleted successfully',
                'redirect_url': reverse('suppliers:purchase_order_list')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)



@login_required
def purchase_order_update_status_view(request, po_id):
    """Update purchase order status - Approve only for managers/admins"""
    if not user_can_view_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    po = get_object_or_404(PurchaseOrder, id=po_id, tenant=tenant)
    old_status = po.status

    if request.method == 'POST':
        try:
            new_status = request.POST.get('status')
            if new_status not in dict(PurchaseOrder.STATUS_CHOICES):
                return JsonResponse({'success': False, 'error': 'Invalid status'}, status=400)

            if new_status == 'approved':
                if not user_can_approve_purchase_orders(request.user):
                    return JsonResponse({
                        'success': False,
                        'error': 'You do not have permission to approve purchase orders.'
                    }, status=403)
                po.approved_by = request.user
                po.approved_at = timezone.now()

            po.status = new_status
            po.save()

            po.supplier.update_financials()

            # ===== SEND NOTIFICATIONS =====
            from accounts.utils import create_po_approval_notification

            if old_status != new_status:
                if new_status == 'pending' and old_status == 'draft':
                    create_po_approval_notification(po, 'submitted')
                elif new_status == 'approved':
                    create_po_approval_notification(po, 'approved', request.user)
                elif new_status == 'cancelled' and old_status == 'pending':
                    create_po_approval_notification(po, 'rejected', request.user)

            return JsonResponse({
                'success': True,
                'message': f'Status updated to {po.get_status_display()}',
                'status': po.status
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def purchase_order_create_view(request):
    """Create a new purchase order"""
    if not user_can_view_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            supplier_id = request.POST.get('supplier')
            expected_delivery = request.POST.get('expected_delivery_date')
            notes = request.POST.get('notes', '').strip()

            if not supplier_id:
                messages.error(request, 'Please select a supplier.')
                return redirect('suppliers:purchase_order_create')

            supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

            # Create purchase order
            po = PurchaseOrder.objects.create(
                tenant=tenant,
                supplier=supplier,
                expected_delivery_date=expected_delivery,
                notes=notes,
                status='draft',
                created_by=request.user
            )

            # Process items
            product_ids = request.POST.getlist('product_ids[]')
            quantities = request.POST.getlist('quantities[]')
            unit_prices = request.POST.getlist('unit_prices[]')

            total = 0
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i] and unit_prices[i]:
                    product = get_object_or_404(Product, id=product_ids[i], tenant=tenant)
                    quantity = Decimal(quantities[i])
                    unit_price = Decimal(unit_prices[i])
                    total_price = quantity * unit_price
                    total += total_price

                    PurchaseOrderItem.objects.create(
                        purchase_order=po,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        total_price=total_price
                    )

            # Update totals
            po.subtotal = total
            po.total_amount = total
            po.save(update_fields=['subtotal', 'total_amount'])

            # Notify the creator that PO was created
            from .utils import create_po_notification

            # Send notification to creator
            from accounts.models import Notification
            Notification.create_notification(
                tenant=tenant,
                user=request.user,
                title=f'PO {po.po_number} Created',
                message=f'Your purchase order {po.po_number} has been created. You can submit it for approval.',
                notification_type='info',
                category='purchase_order',
                link=f'/suppliers/purchase-orders/{po.id}/',
                link_text='View PO',
                icon='fa-file-invoice'
            )

            messages.success(request, f'Purchase Order {po.po_number} created successfully!')
            return redirect('suppliers:purchase_order_detail', po_id=po.id)

        except Exception as e:
            messages.error(request, f'Error creating purchase order: {str(e)}')
            logger.error(f"PO creation error: {str(e)}")
            return redirect('suppliers:purchase_order_create')

    suppliers = Supplier.objects.filter(tenant=tenant, status='active')
    products = Product.objects.filter(tenant=tenant, is_active=True)

    context = {
        'suppliers': suppliers,
        'products': products,
        'title': 'Create Purchase Order - PharmaPro'
    }
    return render(request, 'suppliers/purchase_orders/create.html', context)

@login_required
def purchase_order_approval_view(request):
    """View and approve pending purchase orders - Only for managers and admins"""
    # Check if user has permission to approve
    if not user_can_approve_purchase_orders(request.user):
        messages.error(request, 'You do not have permission to approve purchase orders.')
        return redirect('suppliers:purchase_order_list')

    tenant = request.user.tenant

    # Get all pending purchase orders
    pending_pos = PurchaseOrder.objects.filter(
        tenant=tenant,
        status='pending'
    ).order_by('-created_at')

    # Statistics
    total_pending = pending_pos.count()
    total_draft = PurchaseOrder.objects.filter(tenant=tenant, status='draft').count()
    total_approved = PurchaseOrder.objects.filter(tenant=tenant, status='approved').count()
    total_received = PurchaseOrder.objects.filter(tenant=tenant, status='received').count()

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        pending_pos = pending_pos.filter(
            Q(po_number__icontains=search_query) |
            Q(supplier__name__icontains=search_query) |
            Q(supplier__code__icontains=search_query)
        )

    # Filter by supplier
    supplier_filter = request.GET.get('supplier', '')
    if supplier_filter:
        pending_pos = pending_pos.filter(supplier_id=supplier_filter)

    # Pagination
    paginator = Paginator(pending_pos, 20)
    page_number = request.GET.get('page', 1)
    pos_page = paginator.get_page(page_number)

    suppliers = Supplier.objects.filter(tenant=tenant, status='active')

    context = {
        'purchase_orders': pos_page,
        'total_pending': total_pending,
        'total_draft': total_draft,
        'total_approved': total_approved,
        'total_received': total_received,
        'search_query': search_query,
        'supplier_filter': supplier_filter,
        'suppliers': suppliers,
        'title': 'PO Approvals - PharmaPro'
    }
    return render(request, 'suppliers/purchase_orders/approvals.html', context)


@login_required
def purchase_order_bulk_approve_view(request):
    """Bulk approve purchase orders - Only for managers and admins"""
    # Check if user has permission to approve
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to approve purchase orders.'
        }, status=403)

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            po_ids = request.POST.getlist('po_ids[]')
            if not po_ids:
                return JsonResponse({'success': False, 'error': 'No purchase orders selected'}, status=400)

            approved_count = 0
            for po_id in po_ids:
                try:
                    po = PurchaseOrder.objects.get(id=po_id, tenant=tenant, status='pending')
                    po.status = 'approved'
                    po.approved_by = request.user
                    po.approved_at = timezone.now()
                    po.save()
                    po.supplier.update_financials()
                    approved_count += 1
                except PurchaseOrder.DoesNotExist:
                    continue

            return JsonResponse({
                'success': True,
                'message': f'{approved_count} purchase order(s) approved successfully'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


# ==================== API ENDPOINTS ====================

@login_required
def search_suppliers_api(request):
    """API endpoint to search suppliers"""
    tenant = request.user.tenant
    query = request.GET.get('q', '').strip()

    if not query:
        return JsonResponse({'suppliers': []})

    suppliers = Supplier.objects.filter(
        tenant=tenant,
        status='active'
    ).filter(
        Q(name__icontains=query) |
        Q(code__icontains=query) |
        Q(contact_person__icontains=query)
    )[:20]

    data = []
    for supplier in suppliers:
        data.append({
            'id': str(supplier.id),
            'name': supplier.name,
            'code': supplier.code,
            'contact_person': supplier.contact_person,
            'phone': supplier.phone,
            'email': supplier.email,
        })

    return JsonResponse({'suppliers': data})


@login_required
def search_products_for_supplier_api(request):
    """API endpoint to search products for adding to supplier"""
    tenant = request.user.tenant
    query = request.GET.get('q', '').strip()
    supplier_id = request.GET.get('supplier_id')

    if not query:
        return JsonResponse({'products': []})

    # Start with all active products
    products = Product.objects.filter(
        tenant=tenant,
        is_active=True
    )

    # Filter by search query
    products = products.filter(
        Q(name__icontains=query) |
        Q(sku__icontains=query) |
        Q(barcode__icontains=query)
    )

    # Exclude products already added to this supplier
    if supplier_id:
        try:
            supplier = Supplier.objects.get(id=supplier_id, tenant=tenant)
            existing_product_ids = supplier.supplier_products.values_list('product_id', flat=True)
            products = products.exclude(id__in=existing_product_ids)
        except Supplier.DoesNotExist:
            pass

    products = products[:20]

    data = []
    for product in products:
        data.append({
            'id': str(product.id),
            'name': product.name,
            'sku': product.sku,
            'barcode': product.barcode,
            'price': float(product.price) if product.price else 0,
            'quantity': product.quantity,
            'unit': product.unit.name if product.unit else '',
        })

    return JsonResponse({'products': data})


@login_required
def get_supplier_products_api(request, supplier_id):
    """API endpoint to get products for a supplier"""
    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    products = supplier.supplier_products.filter(is_active=True).select_related('product').values(
        'id', 'product__id', 'product__name', 'product__sku',
        'cost_price', 'min_order_quantity', 'lead_time_days',
        'supplier_product_code', 'is_preferred'
    )

    data = []
    for product in products:
        data.append({
            'id': product['id'],
            'product_id': product['product__id'],
            'product_name': product['product__name'],
            'sku': product['product__sku'],
            'cost_price': float(product['cost_price']),
            'min_order_quantity': float(product['min_order_quantity']),
            'lead_time_days': product['lead_time_days'],
            'supplier_product_code': product['supplier_product_code'],
            'is_preferred': product['is_preferred'],
        })

    return JsonResponse({'products': data})


# ==================== PAYMENTS ====================

# apps/suppliers/views.py - Update supplier_payments_view

@login_required
def supplier_payments_view(request, supplier_id):
    """View all payments for a supplier - Manager, Admin, Superuser only"""
    if not user_can_approve_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)
    payments = supplier.payments.all().order_by('-payment_date')

    # Get purchase orders for the modal dropdown - include all statuses except cancelled
    purchase_orders = supplier.purchase_orders.filter(
        ~Q(status='cancelled')
    ).order_by('-created_at')

    context = {
        'supplier': supplier,
        'payments': payments,
        'purchase_orders': purchase_orders,
        'title': f'Payments - {supplier.name}'
    }
    return render(request, 'suppliers/payments.html', context)

@login_required
def supplier_payment_create_view(request, supplier_id):
    """Create a payment for a supplier - Manager, Admin, Superuser only"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            amount = Decimal(request.POST.get('amount', 0))
            payment_date = request.POST.get('payment_date')
            payment_method = request.POST.get('payment_method')
            reference_number = request.POST.get('reference_number', '').strip()
            notes = request.POST.get('notes', '').strip()
            po_id = request.POST.get('purchase_order')

            if amount <= 0:
                return JsonResponse({
                    'success': False,
                    'error': 'Amount must be greater than zero'
                }, status=400)

            payment = SupplierPayment.objects.create(
                tenant=tenant,
                supplier=supplier,
                amount=amount,
                payment_date=payment_date,
                payment_method=payment_method,
                reference_number=reference_number,
                notes=notes,
                created_by=request.user
            )

            if po_id:
                try:
                    po = PurchaseOrder.objects.get(id=po_id, tenant=tenant)
                    payment.purchase_order = po
                    payment.save()
                except PurchaseOrder.DoesNotExist:
                    pass

            # Update supplier financials
            financials = supplier.update_financials()

            return JsonResponse({
                'success': True,
                'message': f'Payment of Ugx {amount:,.2f} recorded successfully',
                'payment_id': str(payment.id),
                'financials': financials
            })

        except Exception as e:
            logger.error(f"Error creating payment: {str(e)}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    # GET request - return payment form data
    purchase_orders = supplier.purchase_orders.filter(
        status__in=['ordered', 'received', 'partial', 'approved']
    )

    context = {
        'supplier': supplier,
        'purchase_orders': purchase_orders,
        'payment_methods': SupplierPayment.PAYMENT_METHOD_CHOICES,
    }
    return render(request, 'suppliers/payment_create_modal.html', context)


# apps/suppliers/views.py - Add these functions

# apps/suppliers/views.py - Update supplier_approval_list_view

@login_required
def supplier_approval_list_view(request):
    """View and approve suppliers - Only for managers and admins"""
    # Check if user has permission to approve
    if not user_can_approve_purchase_orders(request.user):
        messages.error(request, 'You do not have permission to approve suppliers.')
        return redirect('suppliers:supplier_list')

    tenant = request.user.tenant

    # Get filter for showing approved or pending
    show_approved = request.GET.get('show_approved', 'false') == 'true'

    # Get all suppliers or filter by approval status
    if show_approved:
        suppliers = Supplier.objects.filter(tenant=tenant, is_approved=True)
    else:
        suppliers = Supplier.objects.filter(tenant=tenant, is_approved=False)

    # Statistics
    total_pending = Supplier.objects.filter(tenant=tenant, is_approved=False).count()
    total_approved = Supplier.objects.filter(tenant=tenant, is_approved=True).count()
    total_suppliers = Supplier.objects.filter(tenant=tenant).count()

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        suppliers = suppliers.filter(
            Q(name__icontains=search_query) |
            Q(code__icontains=search_query) |
            Q(contact_person__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )

    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        suppliers = suppliers.filter(status=status_filter)

    # Filter by supplier type
    type_filter = request.GET.get('type', '')
    if type_filter:
        suppliers = suppliers.filter(supplier_type=type_filter)

    suppliers = suppliers.order_by('-created_at')

    paginator = Paginator(suppliers, 20)
    page_number = request.GET.get('page', 1)
    suppliers_page = paginator.get_page(page_number)

    context = {
        'suppliers': suppliers_page,
        'total_pending': total_pending,
        'total_approved': total_approved,
        'total_suppliers': total_suppliers,
        'show_approved': show_approved,
        'search_query': search_query,
        'status_filter': status_filter,
        'type_filter': type_filter,
        'title': 'Supplier Approvals - PharmaPro'
    }
    return render(request, 'suppliers/approvals.html', context)



@login_required
def supplier_approve_view(request, supplier_id):
    """Approve a supplier - Manager, Admin, Superuser only"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            supplier.is_approved = True
            supplier.is_verified = True
            supplier.verified_at = timezone.now()
            supplier.verified_by = request.user
            supplier.save()

            # ===== SEND APPROVAL NOTIFICATION =====
            from accounts.utils import create_supplier_approval_notification
            create_supplier_approval_notification(supplier, 'approved', request.user)

            return JsonResponse({
                'success': True,
                'message': f'Supplier "{supplier.name}" approved successfully'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)



@login_required
def supplier_bulk_approve_view(request):
    """Bulk approve suppliers - Only for managers and admins"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to approve suppliers.'
        }, status=403)

    tenant = request.user.tenant

    if request.method == 'POST':
        try:
            supplier_ids = request.POST.getlist('supplier_ids[]')
            if not supplier_ids:
                return JsonResponse({'success': False, 'error': 'No suppliers selected'}, status=400)

            approved_count = 0
            from .utils import create_supplier_approval_notification

            for supplier_id in supplier_ids:
                try:
                    supplier = Supplier.objects.get(id=supplier_id, tenant=tenant, is_approved=False)
                    supplier.is_approved = True
                    supplier.is_verified = True
                    supplier.verified_at = timezone.now()
                    supplier.verified_by = request.user
                    supplier.save()
                    approved_count += 1

                    # Send notification for each approved supplier
                    create_supplier_approval_notification(supplier, 'approved', request.user)

                except Supplier.DoesNotExist:
                    continue

            return JsonResponse({
                'success': True,
                'message': f'{approved_count} supplier(s) approved successfully'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def supplier_update_financials_view(request, supplier_id):
    """Update supplier financials - Manager, Admin, Superuser only"""
    if not user_can_approve_purchase_orders(request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    supplier = get_object_or_404(Supplier, id=supplier_id, tenant=tenant)

    if request.method == 'POST':
        try:
            financials = supplier.update_financials()
            return JsonResponse({
                'success': True,
                'message': 'Financials updated successfully',
                'financials': financials
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


# Add this import at the top
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone

@login_required
def purchase_order_print_view(request, po_id):
    """Print a single purchase order - Staff, Manager, Admin, Superuser"""
    if not user_can_view_purchase_orders(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    po = get_object_or_404(PurchaseOrder, id=po_id, tenant=tenant)
    items = po.items.all()

    # Get tenant info for print header
    tenant_logo = tenant.logo.url if tenant.logo else None
    company_name = tenant.company_name or tenant.name
    company_address = tenant.company_address or ''
    company_phone = tenant.company_phone or ''
    company_email = tenant.company_email or ''

    context = {
        'po': po,
        'items': items,
        'tenant_logo': tenant_logo,
        'company_name': company_name,
        'company_address': company_address,
        'company_phone': company_phone,
        'company_email': company_email,
        'title': f'{po.po_number} - Print',
        'now': timezone.now()
    }
    return render(request, 'suppliers/purchase_orders/print.html', context)