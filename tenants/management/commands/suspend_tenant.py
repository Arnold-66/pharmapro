# tenants/management/commands/suspend_tenant.py

from django.core.management.base import BaseCommand
from tenants.models import Tenant
from accounts.models import User
from django.contrib.auth import logout
from django.contrib.sessions.models import Session
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Suspend a tenant and logout all users'
    
    def add_arguments(self, parser):
        parser.add_argument('tenant_slug', type=str, help='The slug of the tenant to suspend')
        parser.add_argument('--reason', type=str, default='Administrative action', help='Reason for suspension')
    
    def handle(self, *args, **options):
        tenant_slug = options['tenant_slug']
        reason = options['reason']
        
        try:
            tenant = Tenant.objects.get(slug=tenant_slug)
        except Tenant.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'Tenant with slug "{tenant_slug}" not found'))
            return
        
        self.stdout.write(f'Suspending tenant: {tenant.name}')
        self.stdout.write(f'Reason: {reason}')
        
        # Update tenant status
        tenant.subscription_status = 'suspended'
        tenant.save()
        
        # Logout all users
        users = User.objects.filter(tenant=tenant, is_active=True)
        user_count = users.count()
        
        for user in users:
            # Delete all sessions for this user
            sessions = Session.objects.filter(
                session_data__contains=str(user.id)
            )
            sessions.delete()
            
            # Set user offline
            user.is_online = False
            user.save(update_fields=['is_online'])
        
        self.stdout.write(
            self.style.SUCCESS(f'✅ Tenant "{tenant.name}" suspended successfully')
        )
        self.stdout.write(f'   {user_count} users logged out')