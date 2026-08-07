# apps/sales/urls.py - CORRECTED VERSION

from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    # Dashboard
    path('', views.dashboard_view, name='dashboard'),
    
    # Sales
    path('sales/', views.sale_list_view, name='sale_list'),
    path('sales/create/', views.sale_create_view, name='sale_create'),
    path('sales/<uuid:sale_id>/', views.sale_detail_view, name='sale_detail'),
    # path('sales/<uuid:sale_id>/update/', views.sale_update_view, name='sale_update'),
    path('products/search/', views.search_products, name='search_products'),
    path('<uuid:sale_id>/receipt/', views.sale_receipt_view, name='sale_receipt'),

]