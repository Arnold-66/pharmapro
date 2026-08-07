# tenants/context_processors.py
from .models import TenantSettings

def tenant_context(request):
    """
    Context processor to add tenant to templates.
    """
    if hasattr(request, 'tenant') and request.tenant:
        return {
            'tenant': request.tenant,
        }
    return {}

def tenant_settings(request):
    """
    Context processor to add tenant settings to templates.
    """
    if hasattr(request, 'tenant') and request.tenant:
        try:
            settings = TenantSettings.objects.get(tenant=request.tenant)
            return {
                'tenant_settings': settings,
            }
        except TenantSettings.DoesNotExist:
            pass
    return {}