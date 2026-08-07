# apps/tenants/decorators.py
from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

def check_plan_limit(limit_type, redirect_url=None):
    """
    Decorator to check if tenant has reached a plan limit.
    Usage: @check_plan_limit('max_users')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.tenant:
                return view_func(request, *args, **kwargs)
            
            tenant = request.user.tenant
            from tenants.utils import check_plan_limit as check_limit, get_plan_limit, get_current_usage
            
            if not check_limit(tenant, limit_type):
                current = get_current_usage(tenant, limit_type)
                maximum = get_plan_limit(tenant, limit_type)
                
                # Get the display name for the limit type
                limit_names = {
                    'max_users': 'users',
                    'max_products': 'products',
                    'max_sales': 'sales records'
                }
                limit_name = limit_names.get(limit_type, limit_type.replace('max_', ''))
                
                messages.error(
                    request,
                    f'{limit_name.capitalize()} limit reached! You have {current} {limit_name} '
                    f'and your plan allows only {maximum}. Please upgrade your plan.'
                )
                
                if redirect_url:
                    return redirect(redirect_url)
                return redirect(request.META.get('HTTP_REFERER', reverse('tenants:subscription')))
            
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator