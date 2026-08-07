# apps/accounts/utils.py
import uuid
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.http import Http404


# apps/accounts/utils.py
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.contrib.auth import get_user_model
from .models import Notification
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


def get_user_or_404(user_id, tenant=None):
    """
    Get a user by UUID or raise 404.
    Handles both string and UUID input.
    """
    try:
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise Http404("Invalid user ID format")
    
    try:
        if tenant:
            return User.objects.get(id=user_id, tenant=tenant)
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        raise Http404("User not found")

def get_user_or_redirect(request, user_id, tenant=None):
    """
    Get a user by UUID or redirect to user list with error message.
    """
    try:
        return get_user_or_404(user_id, tenant)
    except Http404 as e:
        messages.error(request, str(e))
        return None


def send_notification_email(notification, user):
    """Send email for a notification"""
    try:
        if not user.email:
            return
        
        context = {
            'user': user,
            'notification': notification,
            'title': notification.title,
            'message': notification.message,
            'link': notification.link,
            'link_text': notification.link_text,
            'site_name': 'PharmaPro',
        }
        
        html_message = render_to_string('accounts/email/notification_email.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject=notification.title,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Error sending notification email to {user.email}: {str(e)}")


def create_approval_notification(tenant, title, message, link, notification_type='warning', 
                                 recipient_roles=None, exclude_users=None):
    """
    Create approval notifications for users with specific roles
    
    Args:
        tenant: Tenant instance
        title: Notification title
        message: Notification message
        link: URL link for the notification
        notification_type: Type of notification
        recipient_roles: List of roles to notify (default: ['admin', 'manager'])
        exclude_users: List of user IDs to exclude
    """
    if recipient_roles is None:
        recipient_roles = ['admin', 'manager']
    
    exclude_users = exclude_users or []
    
    try:
        users = User.objects.filter(
            tenant=tenant,
            is_active=True,
            role__in=recipient_roles
        ).exclude(id__in=exclude_users)
        
        notifications_created = []
        for user in users:
            notification = Notification.create_notification(
                tenant=tenant,
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                category='approval',
                link=link,
                link_text='View Details',
                icon='fa-bell'
            )
            notifications_created.append(notification)
            
            # Send email
            send_notification_email(notification, user)
        
        logger.info(f"Created {len(notifications_created)} approval notifications")
        return notifications_created
        
    except Exception as e:
        logger.error(f"Error creating approval notifications: {str(e)}")
        return []


def create_supplier_approval_notification(supplier, action, actor=None):
    """Create notifications for supplier approval actions"""
    from suppliers.models import Supplier
    
    tenant = supplier.tenant
    supplier_name = supplier.name
    
    configs = {
        'submitted': {
            'title': f'New Supplier Needs Approval: {supplier_name}',
            'message': f'Supplier "{supplier_name}" has been registered by {actor.get_full_name() if actor else "a user"} and needs your approval.',
            'type': 'warning',
            'roles': ['admin', 'manager'],
            'link': '/suppliers/approvals/',
            'icon': 'fa-user-plus'
        },
        'approved': {
            'title': f'Supplier "{supplier_name}" Approved',
            'message': f'Supplier "{supplier_name}" has been approved by {actor.get_full_name() if actor else "Manager"}.',
            'type': 'success',
            'roles': ['staff', 'supervisor', 'admin', 'manager'],
            'link': f'/suppliers/suppliers/{supplier.id}/',
            'icon': 'fa-check-circle'
        },
        'rejected': {
            'title': f'Supplier "{supplier_name}" Rejected',
            'message': f'Supplier "{supplier_name}" has been rejected by {actor.get_full_name() if actor else "Manager"}.',
            'type': 'error',
            'roles': ['staff', 'supervisor'],
            'link': f'/suppliers/suppliers/{supplier.id}/',
            'icon': 'fa-times-circle'
        }
    }
    
    config = configs.get(action)
    if not config:
        logger.warning(f"Unknown supplier action: {action}")
        return []
    
    # Exclude the actor from receiving their own notification
    exclude_users = [actor.id] if actor else []
    
    # Create notifications for specified roles
    notifications = create_approval_notification(
        tenant=tenant,
        title=config['title'],
        message=config['message'],
        link=config['link'],
        notification_type=config['type'],
        recipient_roles=config['roles'],
        exclude_users=exclude_users
    )
    
    # Also notify the creator if supplier was approved/rejected
    if action in ['approved', 'rejected'] and supplier.created_by:
        if supplier.created_by.is_active and supplier.created_by.id not in exclude_users:
            notification = Notification.create_notification(
                tenant=tenant,
                user=supplier.created_by,
                title=config['title'],
                message=config['message'],
                notification_type=config['type'],
                category='supplier',
                link=config['link'],
                link_text='View Supplier',
                icon=config['icon']
            )
            notifications.append(notification)
            send_notification_email(notification, supplier.created_by)
    
    return notifications


def create_po_approval_notification(purchase_order, action, actor=None):
    """Create notifications for PO approval actions"""
    tenant = purchase_order.tenant
    po_number = purchase_order.po_number
    supplier_name = purchase_order.supplier.name
    
    configs = {
        'submitted': {
            'title': f'PO {po_number} Needs Approval',
            'message': f'Purchase Order {po_number} for {supplier_name} has been submitted for approval by {actor.get_full_name() if actor else "a user"}. Total: UGX {purchase_order.total_amount:,.2f}',
            'type': 'warning',
            'roles': ['admin', 'manager'],
            'link': f'/suppliers/purchase-orders/approvals/',
            'icon': 'fa-file-invoice'
        },
        'approved': {
            'title': f'PO {po_number} Approved',
            'message': f'Purchase Order {po_number} for {supplier_name} has been approved by {actor.get_full_name() if actor else "Manager"}.',
            'type': 'success',
            'roles': ['staff', 'supervisor', 'admin', 'manager'],
            'link': f'/suppliers/purchase-orders/{purchase_order.id}/',
            'icon': 'fa-check-circle'
        },
        'rejected': {
            'title': f'PO {po_number} Rejected',
            'message': f'Purchase Order {po_number} for {supplier_name} has been rejected by {actor.get_full_name() if actor else "Manager"}.',
            'type': 'error',
            'roles': ['staff', 'supervisor'],
            'link': f'/suppliers/purchase-orders/{purchase_order.id}/',
            'icon': 'fa-times-circle'
        }
    }
    
    config = configs.get(action)
    if not config:
        logger.warning(f"Unknown PO action: {action}")
        return []
    
    # Exclude the actor from receiving their own notification
    exclude_users = [actor.id] if actor else []
    
    # Create notifications for specified roles
    notifications = create_approval_notification(
        tenant=tenant,
        title=config['title'],
        message=config['message'],
        link=config['link'],
        notification_type=config['type'],
        recipient_roles=config['roles'],
        exclude_users=exclude_users
    )
    
    # Notify the creator
    if purchase_order.created_by and purchase_order.created_by.is_active:
        if purchase_order.created_by.id not in exclude_users:
            notification = Notification.create_notification(
                tenant=tenant,
                user=purchase_order.created_by,
                title=config['title'],
                message=config['message'],
                notification_type=config['type'],
                category='purchase_order',
                link=config['link'],
                link_text='View PO',
                icon=config['icon']
            )
            notifications.append(notification)
            send_notification_email(notification, purchase_order.created_by)
    
    return notifications