# apps/accounts/management/commands/fix_pending_notifications.py
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

User = get_user_model()

class Command(BaseCommand):
    help = 'Fix pending notifications by creating missing ones'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-id',
            type=int,
            help='Fix notifications for a specific tenant ID'
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Fix notifications for a specific user ID'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting notification fix...')
        
        from accounts.models import Notification
        from suppliers.models import Supplier, PurchaseOrder
        
        tenant_id = options.get('tenant_id')
        user_id = options.get('user_id')
        dry_run = options.get('dry_run', False)
        
        users = User.objects.filter(is_active=True)
        if tenant_id:
            users = users.filter(tenant_id=tenant_id)
        if user_id:
            users = users.filter(id=user_id)
        
        fixed_count = 0
        error_count = 0
        
        for user in users:
            self.stdout.write(f'Processing user: {user.email}')
            
            try:
                if not user.tenant:
                    continue
                
                # 1. Check for pending supplier approvals
                pending_suppliers = Supplier.objects.filter(
                    tenant=user.tenant,
                    is_approved=False
                )
                
                for supplier in pending_suppliers:
                    existing = Notification.objects.filter(
                        tenant=user.tenant,
                        user=user,
                        title__icontains=f'Supplier "{supplier.name}" Needs Approval',
                        is_read=False
                    ).exists()
                    
                    if not existing and user.role in ['admin', 'manager']:
                        self.stdout.write(f'  Creating notification for pending supplier: {supplier.name}')
                        if not dry_run:
                            Notification.create_notification(
                                tenant=user.tenant,
                                user=user,
                                title=f'Supplier "{supplier.name}" Needs Approval',
                                message=f'Supplier "{supplier.name}" is pending approval. Please review and approve.',
                                notification_type='warning',
                                category='approval',
                                link='/suppliers/approvals/',
                                link_text='Review Suppliers',
                                icon='fa-user-plus'
                            )
                            fixed_count += 1
                
                # 2. Check for pending purchase orders
                pending_pos = PurchaseOrder.objects.filter(
                    tenant=user.tenant,
                    status='pending'
                )
                
                for po in pending_pos:
                    existing = Notification.objects.filter(
                        tenant=user.tenant,
                        user=user,
                        title__icontains=f'PO {po.po_number} Needs Approval',
                        is_read=False
                    ).exists()
                    
                    if not existing and user.role in ['admin', 'manager']:
                        self.stdout.write(f'  Creating notification for pending PO: {po.po_number}')
                        if not dry_run:
                            Notification.create_notification(
                                tenant=user.tenant,
                                user=user,
                                title=f'PO {po.po_number} Needs Approval',
                                message=f'Purchase Order {po.po_number} for {po.supplier.name} is pending approval.',
                                notification_type='warning',
                                category='purchase_order',
                                link=f'/suppliers/purchase-orders/{po.id}/',
                                link_text='Review PO',
                                icon='fa-file-invoice'
                            )
                            fixed_count += 1
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error processing user {user.email}: {str(e)}'))
                error_count += 1
        
        self.stdout.write(self.style.SUCCESS(f'\n=== COMPLETE ==='))
        self.stdout.write(self.style.SUCCESS(f'Fixed: {fixed_count} notifications'))
        self.stdout.write(self.style.SUCCESS(f'Errors: {error_count} users'))
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes were made'))