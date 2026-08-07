# apps/accounts/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

User = get_user_model()

@receiver(post_save, sender=User)
def create_welcome_notification(sender, instance, created, **kwargs):
    """Create a welcome notification for new users"""
    if created and instance.tenant:
        try:
            from .models import Notification
            
            Notification.create_notification(
                tenant=instance.tenant,
                user=instance,
                title='Welcome to PharmaPro!',
                message=f'Welcome {instance.get_full_name() or instance.username}! Your account has been created successfully.',
                notification_type='success',
                category='user',
                link='/accounts/profile/',
                link_text='View Profile',
                icon='fa-user-plus'
            )
            logger.info(f"Welcome notification created for {instance.email}")
        except Exception as e:
            logger.error(f"Error creating welcome notification: {str(e)}")