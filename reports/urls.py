from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    # Dashboard
    path('', views.report_dashboard_view, name='dashboard'),
    
    # Report types
    path('sales/', views.sales_report_view, name='sales_report'),
    path('inventory/', views.inventory_report_view, name='inventory_report'),
    path('financial/', views.financial_report_view, name='financial_report'),
    
    # Export endpoints
    path('sales/export/pdf/', views.export_sales_pdf, name='export_sales_pdf'),
    path('sales/export/excel/', views.export_sales_excel, name='export_sales_excel'),
    path('inventory/export/pdf/', views.export_inventory_pdf, name='export_inventory_pdf'),
    path('inventory/export/excel/', views.export_inventory_excel, name='export_inventory_excel'),
    path('financial/export/pdf/', views.export_financial_pdf, name='export_financial_pdf'),
    path('financial/export/excel/', views.export_financial_excel, name='export_financial_excel'),
    path('<uuid:report_id>/delete/', views.report_delete_view, name='report_delete'),

    # Report management
    path('list/', views.report_list_view, name='report_list'),
    path('generate/', views.generate_report_view, name='generate_report'),
    path('<uuid:report_id>/', views.report_detail_view, name='report_detail'),
    path('<uuid:report_id>/delete/', views.report_delete_view, name='report_delete'),
    path('<uuid:report_id>/download/', views.download_report, name='download_report'),
]