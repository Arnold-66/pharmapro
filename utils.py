# apps/accounts/utils.py - Create this file

from .models import Notification
from tenants.models import Tenant
from django.utils import timezone
from datetime import timedelta

def create_user_notification(user, title, message, notification_type='info', 
                           category='general', link=None, link_text=None, icon=None):
    """Create a notification for a specific user"""
    return Notification.create_notification(
        tenant=user.tenant,
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        category=category,
        link=link,
        link_text=link_text,
        icon=icon
    )

def create_global_notification(tenant, title, message, notification_type='info',
                              category='general', link=None, link_text=None, icon=None):
    """Create a notification for all users in a tenant"""
    return Notification.create_global_notification(
        tenant=tenant,
        title=title,
        message=message,
        notification_type=notification_type,
        category=category,
        link=link,
        link_text=link_text,
        icon=icon
    )

def create_user_registered_notification(user, tenant):
    """Create notification when a new user registers"""
    create_global_notification(
        tenant=tenant,
        title='New User Registered',
        message=f'{user.get_full_name()} has registered as a new user.',
        notification_type='info',
        category='user',
        link='/accounts/users/',
        link_text='View Users',
        icon='fa-user-plus'
    )

def create_subscription_expiring_notification(tenant, days_left):
    """Create notification when subscription is expiring"""
    create_global_notification(
        tenant=tenant,
        title=f'Subscription Expiring Soon',
        message=f'Your subscription will expire in {days_left} days. Please renew to continue using PharmaPro.',
        notification_type='warning',
        category='subscription',
        link='/tenants/subscription/',
        link_text='Renew Now',
        icon='fa-exclamation-triangle'
    )

def create_low_stock_notification(product, user=None):
    """Create notification for low stock products"""
    title = f'Low Stock Alert: {product.name}'
    message = f'{product.name} has only {product.quantity} items left. Reorder point is {product.reorder_point}.'
    
    if user:
        create_user_notification(
            user=user,
            title=title,
            message=message,
            notification_type='warning',
            category='inventory',
            link=f'/inventory/products/{product.id}/',
            link_text='View Product',
            icon='fa-box'
        )
    else:
        # Send to all admins/managers
        from accounts.models import User
        admin_users = User.objects.filter(tenant=product.tenant, role__in=['admin', 'manager'])
        for admin in admin_users:
            create_user_notification(
                user=admin,
                title=title,
                message=message,
                notification_type='warning',
                category='inventory',
                link=f'/inventory/products/{product.id}/',
                link_text='View Product',
                icon='fa-box'
            )