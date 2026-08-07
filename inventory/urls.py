# apps/inventory/urls.py

from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('', views.dashboard_view, name='dashboard'),
    
    # Categories
    path('categories/', views.category_list_view, name='category_list'),
    path('categories/create/', views.category_create_view, name='category_create'),
    path('categories/<uuid:category_id>/edit/', views.category_edit_view, name='category_edit'),
    path('categories/<uuid:category_id>/delete/', views.category_delete_view, name='category_delete'),
    
    # Products
    path('products/', views.product_list_view, name='product_list'),
    path('products/create/', views.product_create_view, name='product_create'),
    path('products/<uuid:product_id>/', views.product_detail_view, name='product_detail'),
    path('products/<uuid:product_id>/edit/', views.product_edit_view, name='product_edit'),
    path('products/<uuid:product_id>/delete/', views.product_delete_view, name='product_delete'),
    path('products/<uuid:product_id>/stock/', views.product_stock_update_view, name='product_stock_update'),
    path('products/<uuid:product_id>/sale-units/', views.product_sale_units_api, name='product_sale_units_api'),

    # Stock Movements
    path('stock-movements/', views.stock_movement_view, name='stock_movements'),
    path('stock-movements/create/', views.stock_movement_create_view, name='stock_movement_create'),
    
    # Alerts - Use int:alert_id since we changed to AutoField
    path('alerts/', views.alerts_view, name='alerts'),
    path('alerts/<int:alert_id>/mark-read/', views.mark_alert_read_view, name='mark_alert_read'),
    path('alerts/<int:alert_id>/resolve/', views.mark_alert_resolved_view, name='mark_alert_resolved'),
    path('alerts/mark-all-read/', views.mark_all_alerts_read_view, name='mark_all_alerts_read'),
    path('alerts/<uuid:alert_id>/mark-resolved/', views.mark_alert_resolved_view, name='mark_alert_resolved'),

    # Units
    path('units/', views.unit_list_view, name='unit_list'),
    path('units/create/', views.unit_create_view, name='unit_create'),
    path('units/<uuid:unit_id>/edit/', views.unit_edit_view, name='unit_edit'),
    path('units/<uuid:unit_id>/delete/', views.unit_delete_view, name='unit_delete'),
]