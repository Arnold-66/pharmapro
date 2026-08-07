# apps/tenants/signals.py - Add this

from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.contrib.auth import logout
from django.contrib.sessions.models import Session
from .models import Tenant
from .utils import send_subscription_expiry_notification
import logging

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Tenant)
def tenant_pre_save(sender, instance, **kwargs):
    """Store the current subscription status before save"""
    if instance.pk:
        try:
            old_tenant = Tenant.objects.get(pk=instance.pk)
            instance._old_subscription_status = old_tenant.subscription_status
        except Tenant.DoesNotExist:
            pass


@receiver(post_save, sender=Tenant)
def tenant_post_save(sender, instance, created, **kwargs):
    """Send notification when tenant subscription status changes and logout users if suspended"""
    
    # If the tenant was just created, return
    if created:
        return
    
    # Check if subscription status changed
    if hasattr(instance, '_old_subscription_status'):
        old_status = instance._old_subscription_status
        new_status = instance.subscription_status
        
        # If status changed to 'suspended' or 'expired'
        if old_status != new_status and new_status in ['suspended', 'expired']:
            # Send notification
            send_subscription_expiry_notification(instance)
            
            # Logout all users of this tenant
            from accounts.models import User
            from django.contrib.auth import logout
            from django.contrib.sessions.models import Session
            import datetime
            
            # Get all users for this tenant
            users = User.objects.filter(tenant=instance, is_active=True)
            
            # Force logout all users
            for user in users:
                # Delete all sessions for this user
                sessions = Session.objects.filter(
                    session_data__contains=str(user.id)
                )
                sessions.delete()
                
                # Set user offline
                user.is_online = False
                user.save(update_fields=['is_online'])
            
            logger.info(f"All users logged out for tenant {instance.name} - Status changed to {new_status}")


        # apps/tenants/signals.py - Add file deletion signal

from django.db.models.signals import pre_delete
from django.dispatch import receiver
from .models import Tenant

@receiver(pre_delete, sender=Tenant)
def tenant_pre_delete(sender, instance, **kwargs):
    """Delete files when tenant is deleted"""
    if instance.logo:
        instance.logo.delete(save=False)
    if instance.favicon:
        instance.favicon.delete(save=False)