# apps/tenants/utils.py
from .models import Tenant
from accounts.models import User, Notification
from inventory.models import Product
from sales.models import Sale
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


def check_plan_limit(tenant, limit_type):
    """Check if tenant has reached a plan limit"""
    limits = Tenant.PLAN_LIMITS.get(tenant.plan, {})
    max_value = limits.get(limit_type, 0)
    
    if max_value == 0:  # Unlimited
        return True
    
    current_count = 0
    if limit_type == 'max_users':
        current_count = User.objects.filter(tenant=tenant).count()
    elif limit_type == 'max_products':
        current_count = Product.objects.filter(tenant=tenant).count()
    elif limit_type == 'max_sales':
        current_count = Sale.objects.filter(tenant=tenant).count()
    
    return current_count < max_value


def get_plan_limit(tenant, limit_type):
    """Get the maximum allowed for a specific limit type"""
    limits = Tenant.PLAN_LIMITS.get(tenant.plan, {})
    return limits.get(limit_type, 0)


def get_current_usage(tenant, limit_type):
    """Get current usage count for a specific limit type"""
    if limit_type == 'max_users':
        return User.objects.filter(tenant=tenant).count()
    elif limit_type == 'max_products':
        return Product.objects.filter(tenant=tenant).count()
    elif limit_type == 'max_sales':
        return Sale.objects.filter(tenant=tenant).count()
    return 0


# ==================== SUBSCRIPTION EXPIRY NOTIFICATIONS ====================

def send_subscription_expiry_notification(tenant):
    """Send subscription expiry notifications to admins and managers"""
    days_left = tenant.get_days_until_expiry()
    
    if days_left is None or days_left > 3:
        return
    
    # Get all admins and managers
    recipients = User.objects.filter(
        tenant=tenant,
        role__in=['admin', 'manager'],
        is_active=True
    )
    
    # Determine notification type based on days left
    if days_left == 0:
        title = '⚠️ Subscription Expired!'
        message = f'Your subscription for "{tenant.company_name}" has expired. Please renew immediately to avoid service interruption.'
        notification_type = 'error'
        icon = 'fa-times-circle'
        category = 'subscription'
        link = '/tenants/subscription/'
        link_text = 'Renew Now'
    elif days_left <= 3:
        title = f'⚠️ Subscription Expiring Soon!'
        message = f'Your subscription for "{tenant.company_name}" will expire in {days_left} days. Please renew to continue using PharmaPro.'
        notification_type = 'warning'
        icon = 'fa-exclamation-triangle'
        category = 'subscription'
        link = '/tenants/subscription/'
        link_text = 'Renew Now'
    else:
        return
    
    # Send individual notifications to each user
    for user in recipients:
        Notification.create_notification(
            tenant=tenant,
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            category=category,
            link=link,
            link_text=link_text,
            icon=icon
        )
        logger.info(f"Subscription notification sent to {user.email} for tenant {tenant.name}")
    
    # Send email notification
    send_subscription_expiry_email(tenant, days_left, recipients)
    
    # Create global notification for the tenant
    Notification.create_global_notification(
        tenant=tenant,
        title=title,
        message=message,
        notification_type=notification_type,
        category=category,
        link=link,
        link_text=link_text,
        icon=icon
    )
    
    logger.info(f"Subscription expiry notification sent for tenant {tenant.name} - {days_left} days left")


def send_subscription_expiry_email(tenant, days_left, recipients):
    """Send email notification for subscription expiry"""
    try:
        if days_left == 0:
            subject = f'⚠️ PharmaPro Subscription Expired - {tenant.company_name}'
            template = 'tenants/email/subscription_expired.html'
        else:
            subject = f'⚠️ PharmaPro Subscription Expiring Soon - {tenant.company_name}'
            template = 'tenants/email/subscription_expiring.html'
        
        context = {
            'tenant': tenant,
            'days_left': days_left,
            'company_name': tenant.company_name,
            'subscription_end_date': tenant.subscription_end_date or tenant.trial_end_date,
            'site_name': 'PharmaPro',
            'protocol': 'https' if settings.SECURE_SSL_REDIRECT else 'http',
            'domain': settings.ALLOWED_HOSTS[0] if settings.ALLOWED_HOSTS else 'localhost:8000',
        }
        
        html_message = render_to_string(template, context)
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
            logger.info(f"Subscription expiry email sent to {len(recipient_emails)} recipients")
            return True
    except Exception as e:
        logger.error(f"Error sending subscription expiry email: {str(e)}")
        return False


def check_and_send_expiry_notifications():
    """Check all tenants and send expiry notifications"""
    tenants = Tenant.objects.filter(
        subscription_status__in=['active', 'trial']
    )
    
    notified_count = 0
    for tenant in tenants:
        days_left = tenant.get_days_until_expiry()
        
        # Send notification if 3 days or less remaining
        if days_left and days_left <= 3 and days_left > 0:
            send_subscription_expiry_notification(tenant)
            notified_count += 1
        
        # Mark as expired if 0 days left
        if days_left == 0 and tenant.subscription_status != 'expired':
            tenant.subscription_status = 'expired'
            tenant.save()
            send_subscription_expiry_notification(tenant)
            notified_count += 1
    
    return notified_count



def update_storage_usage(tenant, file_size, add=True):
    """
    Update tenant storage usage
    """
    if add:
        tenant.storage_used += file_size
    else:
        tenant.storage_used -= file_size
    tenant.save(update_fields=['storage_used'])
    
    # Check if storage limit is exceeded
    if tenant.storage_used > tenant.max_storage:
        # Send notification about storage limit
        from accounts.models import Notification
        Notification.create_global_notification(
            tenant=tenant,
            title='⚠️ Storage Limit Exceeded',
            message=f'Your organization has exceeded the storage limit of {tenant.max_storage // (1024*1024)}MB. Please delete some files or upgrade your plan.',
            notification_type='warning',
            category='system',
            icon='fa-database'
        )

def get_storage_usage_percentage(tenant):
    """
    Get storage usage percentage
    """
    if tenant.max_storage == 0:
        return 0
    return (tenant.storage_used / tenant.max_storage) * 100