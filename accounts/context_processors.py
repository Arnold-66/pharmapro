# apps/accounts/context_processors.py
from .models import Notification

def notification_context(request):
    """Add notification context to all templates"""
    context = {
        'unread_notifications': 0,
        'pending_suppliers': 0,
        'pending_pos': 0,
    }
    
    if request.user.is_authenticated and request.user.tenant:
        try:
            # Get unread notifications count
            context['unread_notifications'] = Notification.get_unread_count(request.user)
            
            # Get pending supplier approvals
            from suppliers.models import Supplier, PurchaseOrder
            context['pending_suppliers'] = Supplier.objects.filter(
                tenant=request.user.tenant,
                is_approved=False
            ).count()
            
            context['pending_pos'] = PurchaseOrder.objects.filter(
                tenant=request.user.tenant,
                status='pending'
            ).count()
            
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error in notification context: {str(e)}")
    
    return context