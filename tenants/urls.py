# apps/tenants/urls.py
from django.urls import path
from . import views

app_name = 'tenants'

urlpatterns = [
    # Subscription Management
    path('subscription/', views.subscription_view, name='subscription'),
    path('subscription/renew/', views.subscription_renew_view, name='subscription_renew'),
    path('subscription/cancel/', views.subscription_cancel_view, name='subscription_cancel'),
    path('subscription/change-plan/', views.subscription_change_plan_view, name='subscription_change_plan'),
    
    # Webhook
    path('webhook/stripe/', views.stripe_webhook_view, name='stripe_webhook'),
    
    # Superuser Tenant Management
     path('manage/', views.tenant_list_view, name='list'),
    path('manage/<uuid:tenant_id>/', views.tenant_detail_view, name='detail'),
    path('manage/<uuid:tenant_id>/suspend/', views.tenant_suspend_view, name='suspend'),
    path('manage/<uuid:tenant_id>/activate/', views.tenant_activate_view, name='activate'),
    path('manage/<uuid:tenant_id>/delete/', views.tenant_delete_view, name='delete'),
]