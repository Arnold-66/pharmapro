# apps/tenants/management/commands/check_storage.py
from django.core.management.base import BaseCommand
from tenants.models import Tenant
from tenants.utils import update_storage_usage, check_plan_limit
import os

class Command(BaseCommand):
    help = 'Check tenant storage usage and send notifications'

    def handle(self, *args, **options):
        tenants = Tenant.objects.all()
        
        for tenant in tenants:
            # Calculate actual storage used
            total_size = 0
            if tenant.logo and os.path.exists(tenant.logo.path):
                total_size += os.path.getsize(tenant.logo.path)
            if tenant.favicon and os.path.exists(tenant.favicon.path):
                total_size += os.path.getsize(tenant.favicon.path)
            
            # Update storage usage
            if total_size != tenant.storage_used:
                tenant.storage_used = total_size
                tenant.save(update_fields=['storage_used'])
                
                self.stdout.write(f"Updated storage for {tenant.name}: {total_size} bytes")
            
            # Check if storage limit is exceeded
            if tenant.storage_used > tenant.max_storage and tenant.max_storage > 0:
                from accounts.models import Notification
                Notification.create_global_notification(
                    tenant=tenant,
                    title='⚠️ Storage Limit Exceeded',
                    message=f'Your organization has exceeded the storage limit. Please delete some files or upgrade your plan.',
                    notification_type='warning',
                    category='system',
                    icon='fa-database'
                )
                self.stdout.write(f"Storage limit exceeded for {tenant.name}")