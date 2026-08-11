"""
URL configuration for pharma project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# pharma/urls.py
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView

# Import views from correct apps
from accounts.views import login_view, register_view, logout_view,landing_view, dashboard_view

urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),
    
    # Landing Page (from tenants app)
    path('', landing_view, name='landing'),
    
    # Authentication (from accounts app)
    path('login/', login_view, name='login'),
    path('register/', register_view, name='register'),
    path('logout/', logout_view, name='logout'),
    
    # App URLs
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('tenants/', include('tenants.urls', namespace='tenants')),
    path('inventory/', include('inventory.urls', namespace='inventory')),
    path('suppliers/', include('suppliers.urls', namespace='suppliers')),
    path('sales/', include('sales.urls', namespace='sales')),
    path('reports/', include('reports.urls', namespace='reports')),
    
    # # API URLs
    # path('api/accounts/', include('accounts.api_urls', namespace='api_accounts')),
    # path('api/tenants/', include('tenants.api_urls', namespace='api_tenants')),
    # path('api/inventory/', include('inventory.api_urls', namespace='api_inventory')),
    # path('api/suppliers/', include('suppliers.api_urls', namespace='api_suppliers')),
    # path('api/sales/', include('sales.api_urls', namespace='api_sales')),
    # path('api/reports/', include('reports.api_urls', namespace='api_reports')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # Debug toolbar
    if 'debug_toolbar' in settings.INSTALLED_APPS:
        import debug_toolbar
        urlpatterns += [
            path('__debug__/', include(debug_toolbar.urls)),
        ]