# apps/tenants/middleware.py
from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect, render
from django.urls import resolve
from django.http import Http404, HttpResponseRedirect
from django.contrib import messages
from django.urls import reverse
import re

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware to handle tenant identification and subscription expiry.
    """
    
    # URLs that should be accessible even when subscription is expired/suspended
    EXEMPT_URLS = [
        r'^/tenants/subscription/$',
        r'^/tenants/subscription/renew/$',
        r'^/tenants/subscription/cancel/$',
        r'^/tenants/subscription/change-plan/$',
        r'^/accounts/logout/$',
        r'^/accounts/login/$',
        r'^/accounts/verify-email/.*$',
        r'^/accounts/access-denied/$',
        r'^/tenants/webhook/stripe/.*$',
        r'^/admin/.*$',
        r'^/accounts/notifications/.*$',
    ]
    
    def process_request(self, request):
        # Get the tenant from the request
        if hasattr(request, 'user') and request.user.is_authenticated:
            request.tenant = request.user.tenant
        else:
            request.tenant = None
        
        # Identify tenant from host
        self._identify_tenant_from_host(request)
        
        # Check subscription expiry
        if request.user.is_authenticated and request.tenant:
            return self._check_subscription_status(request)
        
        return None
    
    def _identify_tenant_from_host(self, request):
        """Identify tenant from the host/subdomain."""
        host = request.get_host()
        if ':' in host:
            host = host.split(':')[0]
        
        # Check if it's a subdomain
        parts = host.split('.')
        if len(parts) >= 3:
            subdomain = parts[0]
            # Here you could look up the tenant by subdomain
    
    def process_response(self, request, response):
        """Update storage usage if files were uploaded"""

        if hasattr(request, 'tenant') and request.tenant:
            if hasattr(request, 'FILES') and request.FILES:
                total_size = 0

                for file in request.FILES.values():
                    total_size += file.size

                if total_size > 0:
                    from .utils import update_storage_usage
                    update_storage_usage(
                        request.tenant,
                        total_size,
                        add=True
                    )

        return response

    def _check_subscription_status(self, request):
        """Check if subscription is expired or suspended"""
        tenant = request.tenant
        
        # Skip check for exempt URLs
        current_path = request.path_info
        for pattern in self.EXEMPT_URLS:
            if re.match(pattern, current_path):
                return None
        
        # Superusers can bypass all checks
        if request.user.is_superuser:
            return None
        
        # Check if tenant is suspended
        if tenant.subscription_status == 'suspended':
            # Clear session to force re-login
            request.session.flush()  # This clears all session data
            
            # Show suspended page
            context = {
                'tenant': tenant,
                'title': 'Account Suspended - PharmaPro'
            }
            return render(request, 'tenants/tenant_suspended.html', context)
        
        
        

        # Check if tenant is expired
        if tenant.is_expired():
            # Show subscription expired page
            context = {
                'tenant': tenant,
                'title': 'Subscription Expired - PharmaPro'
            }
            return render(request, 'tenants/subscription_expired.html', context)
        
        # Check if subscription is about to expire (3 days warning)
        days_left = tenant.get_days_until_expiry()
        if days_left and days_left <= 3 and days_left > 0:
            # Set warning in session
            request.session['subscription_expiring_soon'] = True
            request.session['subscription_days_left'] = days_left
            
            # Show warning message (once per session)
            if not request.session.get('subscription_warning_shown', False):
                messages.warning(
                    request,
                    f'Your subscription will expire in {days_left} days. Please renew to avoid service interruption.'
                )
                request.session['subscription_warning_shown'] = True
        
        return None