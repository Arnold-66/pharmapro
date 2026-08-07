# tenants/management/commands/check_subscription_expiry.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from tenants.models import Tenant
from tenants.utils import send_subscription_expiry_notification
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Check for expiring subscriptions and send notifications'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--debug',
            action='store_true',
            help='Enable debug mode to see more details',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force check even if days_left is None',
        )
    
    def handle(self, *args, **options):
        self.stdout.write('=' * 60)
        self.stdout.write('Checking subscription expiry status...')
        self.stdout.write('=' * 60)
        
        # Get all tenants
        all_tenants = Tenant.objects.all()
        self.stdout.write(f'Total tenants: {all_tenants.count()}')
        
        # Get active tenants
        tenants = Tenant.objects.filter(
            subscription_status__in=['active', 'trial']
        )
        self.stdout.write(f'Active/Trial tenants: {tenants.count()}')
        
        notified_count = 0
        expired_count = 0
        error_count = 0
        
        for tenant in tenants:
            try:
                self.stdout.write(f'\n--- Processing: {tenant.name} ---')
                self.stdout.write(f'  Status: {tenant.subscription_status}')
                
                days_left = tenant.get_days_until_expiry()
                self.stdout.write(f'  Days left: {days_left}')
                
                if options.get('debug'):
                    self.stdout.write(f'  Subscription end date: {tenant.subscription_end_date}')
                    self.stdout.write(f'  Trial end date: {tenant.trial_end_date}')
                    self.stdout.write(f'  Current time: {timezone.now()}')
                
                if days_left is None:
                    self.stdout.write(self.style.WARNING(f'  ⚠️ Days left is None for {tenant.name}'))
                    if options.get('force'):
                        self.stdout.write('  Force mode enabled, marking as expired')
                        days_left = 0
                    else:
                        continue
                
                # Check if expired
                if days_left <= 0:
                    self.stdout.write(self.style.WARNING(f'  ⚠️ Days left: {days_left} - Tenant is expired'))
                    
                    # Update status to expired if not already
                    if tenant.subscription_status != 'expired':
                        tenant.subscription_status = 'expired'
                        tenant.save()
                        expired_count += 1
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Tenant {tenant.name} marked as expired'))
                    else:
                        self.stdout.write(f'  Tenant already marked as expired')
                
                # Send notifications for expiring soon (3 days or less)
                elif days_left <= 3 and days_left > 0:
                    self.stdout.write(f'  📧 Sending expiry notification - {days_left} days left')
                    try:
                        send_subscription_expiry_notification(tenant)
                        notified_count += 1
                        self.stdout.write(self.style.SUCCESS(f'  ✅ Notification sent to {tenant.name}'))
                    except Exception as e:
                        error_count += 1
                        self.stdout.write(self.style.ERROR(f'  ❌ Error sending notification: {str(e)}'))
                
                else:
                    self.stdout.write(f'  ✅ Tenant is active with {days_left} days remaining')
                    
            except Exception as e:
                error_count += 1
                self.stdout.write(self.style.ERROR(f'  ❌ Error processing tenant {tenant.name}: {str(e)}'))
        
        # Summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write('SUMMARY:')
        self.stdout.write(f'  ✅ Notifications sent: {notified_count}')
        self.stdout.write(f'  ✅ Tenants marked expired: {expired_count}')
        self.stdout.write(f'  ❌ Errors: {error_count}')
        self.stdout.write('=' * 60)
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ Completed: {notified_count} notifications sent, {expired_count} tenants marked as expired'
            )
        )