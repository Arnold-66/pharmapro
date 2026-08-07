# apps/suppliers/utils.py
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
from accounts.models import Notification, User
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


def create_po_notification(po, action, user=None):
    """Create notification for purchase order actions"""
    tenant = po.tenant
    
    if action == 'submitted':
        # Notify all managers and admins
        title = f'New Purchase Order Submitted: {po.po_number}'
        message = f'PO {po.po_number} has been submitted for approval by {po.created_by.get_full_name()}. Total: Ugx {po.total_amount:,.2f}'
        notification_type = 'info'
        category = 'purchase_order'
        icon = 'fa-paper-plane'
        link = f'/suppliers/purchase-orders/{po.id}/'
        link_text = 'Review PO'
        
        # Send to all managers and admins
        recipients = User.objects.filter(
            tenant=tenant,
            role__in=['admin', 'manager'],
            is_active=True
        )
        
        for recipient in recipients:
            Notification.create_notification(
                tenant=tenant,
                user=recipient,
                title=title,
                message=message,
                notification_type=notification_type,
                category=category,
                link=link,
                link_text=link_text,
                icon=icon
            )
            
        # Send email to managers/admins
        send_po_notification_email(po, 'submitted', recipients)
        
        # Also notify the submitter that it was sent
        if po.created_by:
            Notification.create_notification(
                tenant=tenant,
                user=po.created_by,
                title=f'PO {po.po_number} Submitted',
                message=f'Your purchase order {po.po_number} has been submitted for approval.',
                notification_type='success',
                category='purchase_order',
                link=f'/suppliers/purchase-orders/{po.id}/',
                link_text='View PO',
                icon='fa-check-circle'
            )
        
    elif action == 'approved':
        # Notify the creator
        title = f'PO {po.po_number} Approved'
        message = f'Your purchase order {po.po_number} has been approved by {user.get_full_name()}.'
        notification_type = 'success'
        category = 'purchase_order'
        icon = 'fa-check-circle'
        link = f'/suppliers/purchase-orders/{po.id}/'
        link_text = 'View PO'
        
        if po.created_by:
            Notification.create_notification(
                tenant=tenant,
                user=po.created_by,
                title=title,
                message=message,
                notification_type=notification_type,
                category=category,
                link=link,
                link_text=link_text,
                icon=icon
            )
            # Send email to creator
            send_po_notification_email(po, 'approved', [po.created_by])
        
        # Notify all managers/admins that it was approved
        recipients = User.objects.filter(
            tenant=tenant,
            role__in=['admin', 'manager'],
            is_active=True
        ).exclude(id=user.id if user else None)
        
        for recipient in recipients:
            Notification.create_notification(
                tenant=tenant,
                user=recipient,
                title=f'PO {po.po_number} Approved',
                message=f'PO {po.po_number} has been approved by {user.get_full_name()}.',
                notification_type='success',
                category='purchase_order',
                link=link,
                link_text='View PO',
                icon='fa-check-circle'
            )
            
    elif action == 'rejected':
        # Notify the creator
        title = f'PO {po.po_number} Rejected'
        message = f'Your purchase order {po.po_number} has been rejected by {user.get_full_name()}.'
        notification_type = 'error'
        category = 'purchase_order'
        icon = 'fa-times-circle'
        link = f'/suppliers/purchase-orders/{po.id}/'
        link_text = 'View PO'
        
        if po.created_by:
            Notification.create_notification(
                tenant=tenant,
                user=po.created_by,
                title=title,
                message=message,
                notification_type=notification_type,
                category=category,
                link=link,
                link_text=link_text,
                icon=icon
            )
            send_po_notification_email(po, 'rejected', [po.created_by])
            
    elif action == 'ordered':
        title = f'PO {po.po_number} Ordered'
        message = f'PO {po.po_number} has been marked as ordered by {user.get_full_name()}.'
        notification_type = 'info'
        category = 'purchase_order'
        icon = 'fa-truck'
        link = f'/suppliers/purchase-orders/{po.id}/'
        link_text = 'View PO'
        
        if po.created_by:
            Notification.create_notification(
                tenant=tenant,
                user=po.created_by,
                title=title,
                message=message,
                notification_type=notification_type,
                category=category,
                link=link,
                link_text=link_text,
                icon=icon
            )
            
    elif action == 'received':
        title = f'PO {po.po_number} Received'
        message = f'PO {po.po_number} has been marked as received by {user.get_full_name()}.'
        notification_type = 'success'
        category = 'purchase_order'
        icon = 'fa-boxes'
        link = f'/suppliers/purchase-orders/{po.id}/'
        link_text = 'View PO'
        
        if po.created_by:
            Notification.create_notification(
                tenant=tenant,
                user=po.created_by,
                title=title,
                message=message,
                notification_type=notification_type,
                category=category,
                link=link,
                link_text=link_text,
                icon=icon
            )


def send_po_notification_email(po, action, recipients):
    """Send email notification for PO actions"""
    try:
        subject = f'Purchase Order {po.po_number} - {action.upper()}'
        
        context = {
            'po': po,
            'action': action,
            'supplier': po.supplier,
            'total_amount': po.total_amount,
            'created_by': po.created_by,
            'approved_by': po.approved_by if hasattr(po, 'approved_by') else None,
            'po_url': f'/suppliers/purchase-orders/{po.id}/',
            'site_name': 'PharmaPro',
        }
        
        html_message = render_to_string('suppliers/email/po_notification.html', context)
        plain_message = strip_tags(html_message)
        
        recipient_emails = [r.email for r in recipients if r.email]
        
        if recipient_emails:
            send_mail(
                subject,
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                recipient_emails,
                html_message=html_message,
                fail_silently=False
            )
            logger.info(f"PO notification email sent for {po.po_number}")
    except Exception as e:
        logger.error(f"Error sending PO notification email: {str(e)}")