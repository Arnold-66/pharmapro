# apps/suppliers/urls.py
from django.urls import path
from . import views

app_name = 'suppliers'

urlpatterns = [
    # Supplier Management
    path('', views.supplier_list_view, name='supplier_list'),
    path('create/', views.supplier_create_view, name='supplier_create'),
    path('<uuid:supplier_id>/', views.supplier_detail_view, name='supplier_detail'),
    path('<uuid:supplier_id>/edit/', views.supplier_edit_view, name='supplier_edit'),
    path('<uuid:supplier_id>/delete/', views.supplier_delete_view, name='supplier_delete'),
    path('<uuid:supplier_id>/toggle-status/', views.supplier_toggle_status_view, name='supplier_toggle_status'),
    path('<uuid:supplier_id>/approve/', views.supplier_approve_view, name='supplier_approve'),
    path('<uuid:supplier_id>/update-financials/', views.supplier_update_financials_view, name='supplier_update_financials'),
    
    # Supplier Approvals (NEW)
    path('approvals/', views.supplier_approval_list_view, name='supplier_approvals'),
    path('<uuid:supplier_id>/approve/', views.supplier_approve_view, name='supplier_approve'),
    path('bulk-approve/', views.supplier_bulk_approve_view, name='supplier_bulk_approve'),
    
    # Supplier Products
    path('<uuid:supplier_id>/products/add/', views.supplier_product_add_view, name='supplier_product_add'),
    path('products/<uuid:supplier_product_id>/remove/', views.supplier_product_remove_view, name='supplier_product_remove'),
    path('<uuid:supplier_id>/products/api/', views.get_supplier_products_api, name='get_supplier_products_api'),
    
    # Supplier Payments
    path('<uuid:supplier_id>/payments/', views.supplier_payments_view, name='supplier_payments'),
    path('<uuid:supplier_id>/payments/create/', views.supplier_payment_create_view, name='supplier_payment_create'),

    # Purchase Orders
    path('purchase-orders/', views.purchase_order_list_view, name='purchase_order_list'),
    path('purchase-orders/create/', views.purchase_order_create_view, name='purchase_order_create'),
    path('purchase-orders/<uuid:po_id>/', views.purchase_order_detail_view, name='purchase_order_detail'),
    path('purchase-orders/<uuid:po_id>/edit/', views.purchase_order_edit_view, name='purchase_order_edit'),
    path('purchase-orders/<uuid:po_id>/delete/', views.purchase_order_delete_view, name='purchase_order_delete'),
    path('purchase-orders/<uuid:po_id>/update-status/', views.purchase_order_update_status_view, name='purchase_order_update_status'),
    path('purchase-orders/approvals/', views.purchase_order_approval_view, name='purchase_order_approvals'),
    path('purchase-orders/bulk-approve/', views.purchase_order_bulk_approve_view, name='purchase_order_bulk_approve'),

    # API
    path('api/search-products/', views.search_products_for_supplier_api, name='search_products_api'),
    path('api/search-suppliers/', views.search_suppliers_api, name='search_suppliers_api'),
]