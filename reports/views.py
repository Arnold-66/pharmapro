from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, F, Avg, Max, Min
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
from datetime import datetime, timedelta, date
import json
import logging
from io import BytesIO
import base64
import csv

from .models import Report, ReportTemplate
from sales.models import Sale, SaleItem, Payment
from inventory.models import Product, StockMovement, Category
from accounts.models import User

import io
import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

logger = logging.getLogger(__name__)

# Helper function to convert Decimal and datetime for JSON serialization
def convert_for_json(obj):
    """Convert Decimal to float and datetime to string for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: convert_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [convert_for_json(item) for item in obj]
    return obj


@login_required
def report_dashboard_view(request):
    """Reports dashboard with charts and graphs"""
    tenant = request.user.tenant
    
    # Get date range for reports
    today = timezone.now().date()
    start_of_month = today.replace(day=1)
    start_of_week = today - timedelta(days=today.weekday())
    
    # Sales Summary
    total_sales = Sale.objects.filter(tenant=tenant).count()
    total_revenue = Sale.objects.filter(tenant=tenant).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Today's sales
    today_sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date=today
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    # Monthly sales
    monthly_sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=start_of_month
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    # Weekly sales
    weekly_sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=start_of_week
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )
    
    # Sales by status - Convert for JSON
    sales_by_status = list(Sale.objects.filter(tenant=tenant).values('payment_status').annotate(
        count=Count('id'),
        total=Sum('total_amount')
    ))
    sales_by_status = convert_for_json(sales_by_status)
    
    # Monthly sales trend (last 12 months)
    from django.db.models.functions import TruncMonth
    monthly_trend = list(Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=timezone.now() - timedelta(days=365)
    ).annotate(
        month=TruncMonth('sale_date')
    ).values('month').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    ).order_by('month'))
    monthly_trend = convert_for_json(monthly_trend)
    
    # Top selling products
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant
    ).values('product__name', 'product__sku').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_revenue')[:10])
    top_products = convert_for_json(top_products)
    
    # Sales by payment method
    sales_by_payment = list(Payment.objects.filter(
        tenant=tenant
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ))
    sales_by_payment = convert_for_json(sales_by_payment)
    
    # Inventory summary
    total_products = Product.objects.filter(tenant=tenant).count()
    low_stock_count = Product.objects.filter(
        tenant=tenant,
        quantity__lte=F('reorder_point'),
        quantity__gt=0
    ).count()
    out_of_stock_count = Product.objects.filter(tenant=tenant, quantity=0).count()
    total_stock_value = Product.objects.filter(tenant=tenant).aggregate(
        total=Sum(F('quantity') * F('purchase_price'))
    )['total'] or 0
    
    # Stock by category - Convert for JSON
    stock_by_category = list(Product.objects.filter(
        tenant=tenant
    ).values('category__name').annotate(
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('purchase_price'))
    ).order_by('-total_value'))
    stock_by_category = convert_for_json(stock_by_category)
    
    # Recent activities
    recent_sales = Sale.objects.filter(tenant=tenant).order_by('-sale_date')[:5]
    recent_movements = StockMovement.objects.filter(tenant=tenant).order_by('-created_at')[:5]
    
    context = {
        'total_sales': total_sales,
        'total_revenue': total_revenue,
        'today_sales': today_sales['total'] or 0,
        'today_count': today_sales['count'] or 0,
        'monthly_sales': monthly_sales['total'] or 0,
        'monthly_count': monthly_sales['count'] or 0,
        'weekly_sales': weekly_sales['total'] or 0,
        'weekly_count': weekly_sales['count'] or 0,
        'sales_by_status': json.dumps(sales_by_status),
        'monthly_trend': json.dumps(monthly_trend),
        'top_products': json.dumps(top_products),
        'sales_by_payment': json.dumps(sales_by_payment),
        'total_products': total_products,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'total_stock_value': total_stock_value,
        'stock_by_category': json.dumps(stock_by_category),
        'recent_sales': recent_sales,
        'recent_movements': recent_movements,
        'title': 'Reports Dashboard - PharmaPro'
    }
    return render(request, 'reports/dashboard.html', context)


@login_required
def sales_report_view(request):
    """Sales report with filters"""
    tenant = request.user.tenant
    sales = Sale.objects.filter(tenant=tenant)
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status = request.GET.get('status')
    payment_method = request.GET.get('payment_method')
    
    # Apply filters
    if date_from:
        sales = sales.filter(sale_date__date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__date__lte=date_to)
    if status:
        sales = sales.filter(payment_status=status)
    if payment_method:
        sales = sales.filter(payment_method=payment_method)
    
    # Aggregations
    total_sales = sales.count()
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    average_sale = total_revenue / total_sales if total_sales > 0 else 0
    
    # Sales by day (for chart) - Convert for JSON
    from django.db.models.functions import TruncDate
    sales_by_day = list(sales.annotate(
        date=TruncDate('sale_date')
    ).values('date').annotate(
        total=Sum('total_amount'),
        count=Count('id')
    ).order_by('date'))
    sales_by_day = convert_for_json(sales_by_day)
    
    # Pagination
    paginator = Paginator(sales, 20)
    page_number = request.GET.get('page', 1)
    sales_page = paginator.get_page(page_number)
    
    context = {
        'sales': sales_page,
        'total_sales': total_sales,
        'total_revenue': total_revenue,
        'total_tax': total_tax,
        'total_discount': total_discount,
        'average_sale': average_sale,
        'sales_by_day': json.dumps(sales_by_day),
        'date_from': date_from,
        'date_to': date_to,
        'status': status,
        'payment_method': payment_method,
        'title': 'Sales Report - PharmaPro'
    }
    return render(request, 'reports/sales_report.html', context)


@login_required
def inventory_report_view(request):
    """Inventory report with filters"""
    tenant = request.user.tenant
    products = Product.objects.filter(tenant=tenant)
    
    # Get filter parameters
    category = request.GET.get('category')
    status = request.GET.get('status')
    stock_filter = request.GET.get('stock_filter')
    
    # Apply filters
    if category:
        products = products.filter(category_id=category)
    if status:
        products = products.filter(status=status)
    if stock_filter == 'low':
        products = products.filter(quantity__lte=F('reorder_point'), quantity__gt=0)
    elif stock_filter == 'out':
        products = products.filter(quantity=0)
    elif stock_filter == 'in':
        products = products.filter(quantity__gt=0)
    
    # Add total_value to each product
    for product in products:
        product.total_value = product.quantity * product.purchase_price
    
    # Aggregations
    total_products = products.count()
    total_stock_value = products.aggregate(total=Sum(F('quantity') * F('purchase_price')))['total'] or 0
    total_stock_quantity = products.aggregate(total=Sum('quantity'))['total'] or 0
    avg_price = products.aggregate(avg=Avg('selling_price'))['avg'] or 0
    
    # Stock by category - Convert for JSON
    stock_by_category = list(products.values('category__name').annotate(
        count=Count('id'),
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('purchase_price'))
    ).order_by('-total_value'))
    stock_by_category = convert_for_json(stock_by_category)
    
    # Products with low stock
    low_stock_products = products.filter(quantity__lte=F('reorder_point')).order_by('quantity')[:10]
    
    # Pagination
    paginator = Paginator(products, 20)
    page_number = request.GET.get('page', 1)
    products_page = paginator.get_page(page_number)
    
    categories = Category.objects.filter(tenant=tenant)
    
    context = {
        'products': products_page,
        'total_products': total_products,
        'total_stock_value': total_stock_value,
        'total_stock_quantity': total_stock_quantity,
        'avg_price': avg_price,
        'stock_by_category': json.dumps(stock_by_category),
        'low_stock_products': low_stock_products,
        'categories': categories,
        'category': category,
        'status': status,
        'stock_filter': stock_filter,
        'title': 'Inventory Report - PharmaPro'
    }
    return render(request, 'reports/inventory_report.html', context)

@login_required
def financial_report_view(request):
    """Financial report with charts - Enhanced with detailed revenue breakdown"""
    tenant = request.user.tenant
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    selected_year = request.GET.get('year')
    selected_month = request.GET.get('month')
    
    # Get available years for filter (from all sales)
    available_years = Sale.objects.filter(
        tenant=tenant
    ).dates('sale_date', 'year', order='DESC').distinct()
    
    # Build years list
    years_list = []
    for year in available_years:
        if year.year not in years_list:
            years_list.append(year.year)
    
    # Get earliest and latest sale dates
    earliest_sale = Sale.objects.filter(tenant=tenant).order_by('sale_date').first()
    latest_sale = Sale.objects.filter(tenant=tenant).order_by('-sale_date').first()
    
    today = timezone.now().date()
    current_month_start = today.replace(day=1)
    
    # ===== DETERMINE FILTER TYPE =====
    # Check if date fields are empty or empty strings
    has_date_from = date_from and date_from != ''
    has_date_to = date_to and date_to != ''
    has_year = selected_year and selected_year != ''
    has_month = selected_month and selected_month != ''
    
    # Scenario 1: "All" - no filters at all (all fields empty)
    if not has_date_from and not has_date_to and not has_year and not has_month:
        # Show ALL data
        if earliest_sale and latest_sale:
            date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
            date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            date_from = current_month_start.isoformat()
            date_to = today.isoformat()
    
    # Scenario 2: Year + Month filter
    elif has_year and has_month and not has_date_from and not has_date_to:
        import calendar
        date_from = f"{selected_year}-{str(selected_month).zfill(2)}-01"
        last_day = calendar.monthrange(int(selected_year), int(selected_month))[1]
        date_to = f"{selected_year}-{str(selected_month).zfill(2)}-{last_day}"
    
    # Scenario 3: Year only filter
    elif has_year and not has_month and not has_date_from and not has_date_to:
        date_from = f"{selected_year}-01-01"
        date_to = f"{selected_year}-12-31"
    
    # Scenario 4: Date range filter (both dates provided)
    elif has_date_from and has_date_to:
        # Use the provided dates
        pass
    
    # Scenario 5: Only date_from provided
    elif has_date_from and not has_date_to:
        date_to = today.isoformat()
    
    # Scenario 6: Only date_to provided
    elif not has_date_from and has_date_to:
        if earliest_sale:
            date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            date_from = current_month_start.isoformat()
    
    # Ensure date_from and date_to are set
    if not date_from or date_from == '':
        if earliest_sale:
            date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            date_from = current_month_start.isoformat()
    if not date_to or date_to == '':
        if latest_sale:
            date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            date_to = today.isoformat()
    
    # Convert date strings to date objects
    try:
        from_date_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
        to_date_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
    except ValueError:
        if earliest_sale and latest_sale:
            from_date_obj = earliest_sale.sale_date.date()
            to_date_obj = latest_sale.sale_date.date()
            date_from = from_date_obj.isoformat()
            date_to = to_date_obj.isoformat()
        else:
            from_date_obj = current_month_start
            to_date_obj = today
            date_from = from_date_obj.isoformat()
            date_to = to_date_obj.isoformat()
    
    # Filter using datetime range
    from_datetime = timezone.make_aware(datetime.combine(from_date_obj, datetime.min.time()))
    to_datetime = timezone.make_aware(datetime.combine(to_date_obj, datetime.max.time()))
    
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=from_datetime,
        sale_date__lte=to_datetime
    )
    
    # ===== REVENUE BREAKDOWN =====
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_subtotal = sales.aggregate(total=Sum('subtotal'))['total'] or 0
    
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date_obj,
        created_at__date__lte=to_date_obj
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    net_revenue = total_revenue - total_tax - total_discount
    
    # ... rest of the calculations remain the same ...
    # (revenue_by_category, revenue_by_product, payment_breakdown, etc.)
    
    # ===== OUTSTANDING PAYMENTS =====
    outstanding = Sale.objects.filter(
        tenant=tenant,
        balance_due__gt=0
    ).aggregate(
        total=Sum('balance_due'),
        count=Count('id')
    )
    outstanding_total = outstanding['total'] or 0
    outstanding_count = outstanding['count'] or 0
    
    # ===== COLLECTION RATE =====
    if total_revenue > 0:
        collection_rate = (total_paid / total_revenue) * 100
    else:
        collection_rate = 0
    
    if collection_rate >= 80:
        collection_status = 'good'
        collection_icon = '✅'
    elif collection_rate >= 50:
        collection_status = 'warning'
        collection_icon = '⚠️'
    else:
        collection_status = 'danger'
        collection_icon = '❌'
    
    # ===== GROSS VS NET PROFIT =====
    cogs = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0
    
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    total_orders = sales.count()
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    # ===== REVENUE BY DAY =====
    from django.db.models.functions import TruncDate
    revenue_by_day = list(sales.annotate(
        date=TruncDate('sale_date')
    ).values('date').annotate(
        revenue=Sum('total_amount'),
        tax=Sum('tax_amount'),
        discount=Sum('discount_amount'),
        count=Count('id')
    ).order_by('date'))
    revenue_by_day = convert_for_json(revenue_by_day)
    
    # ===== REVENUE BY CATEGORY =====
    revenue_by_category = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__category__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity'),
        total_cost=Sum(F('quantity') * F('product__purchase_price'))
    ).order_by('-total_revenue'))
    revenue_by_category = convert_for_json(revenue_by_category)
    
    # ===== REVENUE BY PRODUCT =====
    revenue_by_product = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__name', 'product__sku').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue')[:10])
    revenue_by_product = convert_for_json(revenue_by_product)
    
    # ===== PAYMENT BREAKDOWN =====
    payment_breakdown = list(Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date_obj,
        created_at__date__lte=to_date_obj
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    payment_breakdown = convert_for_json(payment_breakdown)
    
    # ===== TOP CUSTOMERS =====
    top_customers = list(sales.values('customer_name').annotate(
        total_spent=Sum('total_amount'),
        order_count=Count('id')
    ).filter(customer_name__isnull=False).exclude(customer_name='').order_by('-total_spent')[:10])
    top_customers = convert_for_json(top_customers)
    
    # ===== PREVIOUS PERIOD COMPARISON =====
    try:
        days_diff = (to_date_obj - from_date_obj).days
        prev_from = from_date_obj - timedelta(days=days_diff + 1)
        prev_to = from_date_obj - timedelta(days=1)
        
        prev_from_datetime = timezone.make_aware(datetime.combine(prev_from, datetime.min.time()))
        prev_to_datetime = timezone.make_aware(datetime.combine(prev_to, datetime.max.time()))
        
        prev_sales = Sale.objects.filter(
            tenant=tenant,
            sale_date__gte=prev_from_datetime,
            sale_date__lte=prev_to_datetime
        )
        prev_revenue = prev_sales.aggregate(total=Sum('total_amount'))['total'] or 0
        
        revenue_change = total_revenue - prev_revenue
        revenue_change_percent = (revenue_change / prev_revenue * 100) if prev_revenue > 0 else 0
    except:
        prev_revenue = 0
        revenue_change = 0
        revenue_change_percent = 0
    
    total_sales_count = sales.count()
    
    months = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    
    context = {
        'total_revenue': total_revenue,
        'total_tax': total_tax,
        'total_discount': total_discount,
        'total_paid': total_paid,
        'net_revenue': net_revenue,
        'total_sales_count': total_sales_count,
        'total_orders': total_orders,
        'average_order_value': average_order_value,
        'revenue_by_category': json.dumps(revenue_by_category),
        'revenue_by_product': json.dumps(revenue_by_product),
        'payment_breakdown': json.dumps(payment_breakdown),
        'revenue_by_day': json.dumps(revenue_by_day),
        'top_customers': json.dumps(top_customers),
        'cogs': cogs,
        'gross_profit': gross_profit,
        'gross_margin': gross_margin,
        'prev_revenue': prev_revenue,
        'revenue_change': revenue_change,
        'revenue_change_percent': revenue_change_percent,
        'outstanding_total': outstanding_total,
        'outstanding_count': outstanding_count,
        'date_from': date_from,
        'date_to': date_to,
        'has_data': total_revenue > 0 or total_sales_count > 0,
        'collection_rate': collection_rate,
        'collection_status': collection_status,
        'collection_icon': collection_icon,
        'available_years': years_list,
        'selected_year': selected_year,
        'selected_month': selected_month,
        'months': months,
        'title': 'Financial Report - PharmaPro'
    }
    return render(request, 'reports/financial_report.html', context)


@login_required
def report_list_view(request):
    """List all saved reports"""
    tenant = request.user.tenant
    reports = Report.objects.filter(tenant=tenant)
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        reports = reports.filter(
            Q(name__icontains=search_query) |
            Q(type__icontains=search_query)
        )
    
    # Filter by type
    type_filter = request.GET.get('type', '')
    if type_filter:
        reports = reports.filter(type=type_filter)
    
    paginator = Paginator(reports, 20)
    page_number = request.GET.get('page', 1)
    reports_page = paginator.get_page(page_number)
    
    context = {
        'reports': reports_page,
        'search_query': search_query,
        'type_filter': type_filter,
        'title': 'Saved Reports - PharmaPro'
    }
    return render(request, 'reports/report_list.html', context)


@login_required
def generate_report_view(request):
    """Generate a new report"""
    tenant = request.user.tenant
    
    if request.method == 'POST':
        try:
            report_type = request.POST.get('report_type')
            report_name = request.POST.get('report_name')
            date_from = request.POST.get('date_from')
            date_to = request.POST.get('date_to')
            format_type = request.POST.get('format', 'pdf')
            
            # Generate report data first
            if report_type == 'sales':
                data = generate_sales_report_data(tenant, date_from, date_to)
            elif report_type == 'inventory':
                data = generate_inventory_report_data(tenant)
            elif report_type == 'financial':
                data = generate_financial_report_data(tenant, date_from, date_to)
            else:
                data = {}
            
            # CONVERT DECIMAL TO FLOAT FOR JSON SERIALIZATION
            data = convert_for_json(data)
            
            # Create report record with parameters
            report = Report.objects.create(
                tenant=tenant,
                name=report_name or f"{report_type.title()} Report - {timezone.now().strftime('%Y-%m-%d')}",
                type=report_type,
                format=format_type,
                filters={
                    'date_from': date_from,
                    'date_to': date_to,
                },
                parameters=data,
                created_by=request.user
            )
            
            # Generate the actual file based on type and format
            if format_type == 'pdf':
                if report_type == 'sales':
                    file_content = generate_sales_pdf_content(tenant, date_from, date_to)
                elif report_type == 'inventory':
                    file_content = generate_inventory_pdf_content(tenant)
                elif report_type == 'financial':
                    file_content = generate_financial_pdf_content(tenant, date_from, date_to)
                else:
                    file_content = None
                    
                if file_content:
                    from django.core.files.base import ContentFile
                    filename = f"{report_name}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                    report.file.save(filename, ContentFile(file_content))
                    report.last_generated = timezone.now()
                    report.save()
            
            elif format_type == 'excel':
                if report_type == 'sales':
                    file_content = generate_sales_excel_content(tenant, date_from, date_to)
                elif report_type == 'inventory':
                    file_content = generate_inventory_excel_content(tenant)
                elif report_type == 'financial':
                    file_content = generate_financial_excel_content(tenant, date_from, date_to)
                else:
                    file_content = None
                    
                if file_content:
                    from django.core.files.base import ContentFile
                    filename = f"{report_name}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                    report.file.save(filename, ContentFile(file_content))
                    report.last_generated = timezone.now()
                    report.save()
            
            elif format_type == 'csv':
                if report_type == 'sales':
                    file_content = generate_sales_csv(tenant, date_from, date_to)
                elif report_type == 'inventory':
                    file_content = generate_inventory_csv(tenant)
                elif report_type == 'financial':
                    file_content = generate_financial_csv(tenant, date_from, date_to)
                else:
                    file_content = None
                    
                if file_content:
                    from django.core.files.base import ContentFile
                    filename = f"{report_name}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
                    report.file.save(filename, ContentFile(file_content))
                    report.last_generated = timezone.now()
                    report.save()
            
            messages.success(request, f'Report "{report.name}" generated successfully!')
            return redirect('reports:report_detail', report_id=report.id)
            
        except Exception as e:
            messages.error(request, f'Error generating report: {str(e)}')
            logger.error(f"Report generation error: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
    
    # Get categories for filter dropdown
    categories = Category.objects.filter(tenant=request.user.tenant)
    
    context = {
        'categories': categories,
        'title': 'Generate Report - PharmaPro'
    }
    return render(request, 'reports/generate_report.html', context)


@login_required
def report_detail_view(request, report_id):
    """View report details"""
    tenant = request.user.tenant
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    
    # Ensure parameters is a dict
    if not report.parameters:
        report.parameters = {}
    
    # If report has no parameters but has a file, generate preview from file
    if report.file and not report.parameters:
        try:
            # Try to extract preview data based on report type
            if report.type == 'sales':
                report.parameters = generate_sales_report_data(
                    tenant, 
                    report.filters.get('date_from'), 
                    report.filters.get('date_to')
                )
            elif report.type == 'inventory':
                report.parameters = generate_inventory_report_data(tenant)
            elif report.type == 'financial':
                report.parameters = generate_financial_report_data(
                    tenant,
                    report.filters.get('date_from'),
                    report.filters.get('date_to')
                )
            report.save()
        except Exception as e:
            logger.error(f"Error generating preview: {str(e)}")
            report.parameters = {}
    
    context = {
        'report': report,
        'title': f'{report.name} - PharmaPro'
    }
    return render(request, 'reports/report_detail.html', context)


@login_required
def report_delete_view(request, report_id):
    """Delete a report"""
    tenant = request.user.tenant
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    
    if request.method == 'POST':
        try:
            report_name = report.name
            report.delete()
            messages.success(request, f'Report "{report_name}" deleted successfully!')
            return redirect('reports:report_list')
        except Exception as e:
            messages.error(request, f'Error deleting report: {str(e)}')
            return redirect('reports:report_detail', report_id=report_id)
    
    context = {
        'report': report,
        'title': 'Delete Report - PharmaPro'
    }
    return render(request, 'reports/report_delete.html', context)


@login_required
def download_report(request, report_id):
    """Download a saved report"""
    tenant = request.user.tenant
    report = get_object_or_404(Report, id=report_id, tenant=tenant)
    
    if report.file:
        response = HttpResponse(report.file, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{report.name}.{report.format}"'
        return response
    
    messages.error(request, 'No file found for this report.')
    return redirect('reports:report_detail', report_id=report_id)


# ============= DATA GENERATION FUNCTIONS =============

def generate_sales_report_data(tenant, date_from, date_to):
    """Generate sales report data"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_sales = sales.count()
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    
    # Top products
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__date__gte=date_from,
        sale__sale_date__date__lte=date_to
    ).values('product__name').annotate(
        total_quantity=Sum('quantity'),
        total_revenue=Sum('total_price')
    ).order_by('-total_revenue')[:10])
    
    for product in top_products:
        product['name'] = product.get('product__name', 'Unknown')
    
    top_products = convert_for_json(top_products)
    
    return {
        'total_revenue': float(total_revenue),
        'total_sales': total_sales,
        'total_tax': float(total_tax),
        'total_discount': float(total_discount),
        'average_sale': float(total_revenue / total_sales) if total_sales > 0 else 0,
        'top_products': top_products,
        'date_from': date_from,
        'date_to': date_to
    }


def generate_inventory_report_data(tenant):
    """Generate inventory report data"""
    products = Product.objects.filter(tenant=tenant)
    
    total_products = products.count()
    total_stock_value = products.aggregate(total=Sum(F('quantity') * F('purchase_price')))['total'] or 0
    total_quantity = products.aggregate(total=Sum('quantity'))['total'] or 0
    
    stock_by_category = list(products.values('category__name').annotate(
        count=Count('id'),
        total_quantity=Sum('quantity'),
        total_value=Sum(F('quantity') * F('purchase_price'))
    ).order_by('-total_value'))
    stock_by_category = convert_for_json(stock_by_category)
    
    low_stock = list(products.filter(
        quantity__lte=F('reorder_point')
    ).values('name', 'sku', 'quantity', 'reorder_point'))
    low_stock = convert_for_json(low_stock)
    
    return {
        'total_products': total_products,
        'total_stock_value': float(total_stock_value),
        'total_quantity': float(total_quantity),
        'stock_by_category': stock_by_category,
        'low_stock': low_stock
    }


def generate_financial_report_data(tenant, date_from, date_to):
    """Generate financial report data"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    
    payments = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    )
    
    total_paid = payments.aggregate(total=Sum('amount'))['total'] or 0
    
    payment_breakdown = list(payments.values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    payment_breakdown = convert_for_json(payment_breakdown)
    
    return {
        'total_revenue': float(total_revenue),
        'total_tax': float(total_tax),
        'total_discount': float(total_discount),
        'total_paid': float(total_paid),
        'payment_breakdown': payment_breakdown,
        'date_from': date_from,
        'date_to': date_to
    }


# ============= PDF CONTENT GENERATION FUNCTIONS =============

def generate_sales_pdf_content(tenant, date_from, date_to):
    """Generate sales report PDF content as bytes"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    elements.append(Paragraph(f"Sales Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_count = sales.count()
    
    summary_data = [
        ['Total Sales', 'Total Revenue', 'Average Sale'],
        [str(total_count), f'Ugx {total_revenue:,.2f}', f'Ugx {(total_revenue/total_count):,.2f}' if total_count > 0 else 'Ugx 0.00']
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    table_data = [['Invoice', 'Customer', 'Date', 'Total', 'Status']]
    for sale in sales[:100]:
        table_data.append([
            sale.invoice_number,
            sale.customer_name or 'Walk-in',
            sale.sale_date.strftime('%Y-%m-%d'),
            f'Ugx {sale.total_amount:,.2f}',
            sale.get_payment_status_display()
        ])
    
    sales_table = Table(table_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    sales_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    elements.append(sales_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


def generate_inventory_pdf_content(tenant):
    """Generate inventory report PDF content as bytes"""
    products = Product.objects.filter(tenant=tenant)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    elements.append(Paragraph(f"Inventory Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    total_value = products.aggregate(total=Sum(F('quantity') * F('purchase_price')))['total'] or 0
    total_quantity = products.aggregate(total=Sum('quantity'))['total'] or 0
    
    summary_data = [
        ['Total Products', 'Total Quantity', 'Total Value'],
        [str(products.count()), str(int(total_quantity)), f'Ugx {total_value:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    table_data = [['Product', 'SKU', 'Quantity', 'Price', 'Value', 'Status']]
    for product in products[:100]:
        value = product.quantity * product.purchase_price
        table_data.append([
            product.name,
            product.sku,
            str(int(product.quantity)),
            f'Ugx {product.purchase_price:,.2f}',
            f'Ugx {value:,.2f}',
            product.get_status_display()
        ])
    
    product_table = Table(table_data, colWidths=[2*inch, 1.5*inch, 1*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    elements.append(product_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


def generate_financial_pdf_content(tenant, date_from, date_to):
    """Generate financial report PDF content with detailed breakdowns"""
    # Convert date strings to date objects
    try:
        from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        from_date = timezone.now().date().replace(day=1)
        to_date = timezone.now().date()
    
    from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
    to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))
    
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=from_datetime,
        sale_date__lte=to_datetime
    )
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'Heading2',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=15
    )
    normal_style = styles['Normal']
    
    elements.append(Paragraph(f"Financial Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", normal_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", normal_style))
    elements.append(Spacer(1, 20))
    
    # ===== SUMMARY STATISTICS =====
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_orders = sales.count()
    avg_order = total_revenue / total_orders if total_orders > 0 else 0
    
    # COGS and Gross Profit
    cogs = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0
    
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Payments
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    outstanding = Sale.objects.filter(
        tenant=tenant,
        balance_due__gt=0
    ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    collection_rate = (total_paid / total_revenue * 100) if total_revenue > 0 else 0
    
    elements.append(Paragraph("Financial Summary", heading_style))
    summary_data = [
        ['Metric', 'Amount'],
        ['Total Revenue', f'Ugx {total_revenue:,.2f}'],
        ['Total Tax', f'Ugx {total_tax:,.2f}'],
        ['Total Discount', f'Ugx {total_discount:,.2f}'],
        ['Net Revenue', f'Ugx {(total_revenue - total_tax - total_discount):,.2f}'],
        ['Cost of Goods Sold (COGS)', f'Ugx {cogs:,.2f}'],
        ['Gross Profit', f'Ugx {gross_profit:,.2f}'],
        ['Gross Margin', f'{gross_margin:.1f}%'],
        ['Total Orders', str(total_orders)],
        ['Average Order Value', f'Ugx {avg_order:,.2f}'],
        ['Total Received', f'Ugx {total_paid:,.2f}'],
        ['Outstanding', f'Ugx {outstanding:,.2f}'],
        ['Collection Rate', f'{collection_rate:.1f}%'],
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    # ===== REVENUE BY CATEGORY =====
    revenue_by_category = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__category__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue'))
    
    if revenue_by_category:
        elements.append(Paragraph("Revenue by Category", heading_style))
        cat_data = [['Category', 'Revenue', 'Quantity']]
        for item in revenue_by_category[:15]:
            cat_data.append([
                item['product__category__name'] or 'Uncategorized',
                f'Ugx {item["total_revenue"]:,.2f}',
                str(int(item['total_quantity'] or 0))
            ])
        
        cat_table = Table(cat_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(cat_table)
        elements.append(Spacer(1, 20))
    
    # ===== REVENUE BY PAYMENT METHOD =====
    revenue_by_payment = list(Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    
    if revenue_by_payment:
        elements.append(Paragraph("Revenue by Payment Method", heading_style))
        pay_data = [['Payment Method', 'Total', 'Count']]
        for item in revenue_by_payment:
            pay_data.append([
                item['method'].replace('_', ' ').title(),
                f'Ugx {item["total"]:,.2f}',
                str(item['count'])
            ])
        
        pay_table = Table(pay_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        pay_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2ecc71')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(pay_table)
        elements.append(Spacer(1, 20))
    
    # ===== TOP 10 PRODUCTS =====
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue')[:10])
    
    if top_products:
        elements.append(Paragraph("Top 10 Products", heading_style))
        prod_data = [['Product', 'Revenue', 'Quantity']]
        for item in top_products:
            prod_data.append([
                item['product__name'] or 'Unknown',
                f'Ugx {item["total_revenue"]:,.2f}',
                str(int(item['total_quantity'] or 0))
            ])
        
        prod_table = Table(prod_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        prod_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f39c12')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(prod_table)
        elements.append(Spacer(1, 20))
    
    # ===== TOP CUSTOMERS =====
    top_customers = list(sales.values('customer_name').annotate(
        total_spent=Sum('total_amount'),
        order_count=Count('id')
    ).filter(customer_name__isnull=False).exclude(customer_name='').order_by('-total_spent')[:10])
    
    if top_customers:
        elements.append(Paragraph("Top Customers", heading_style))
        cust_data = [['Customer', 'Total Spent', 'Orders']]
        for item in top_customers:
            cust_data.append([
                item['customer_name'],
                f'Ugx {item["total_spent"]:,.2f}',
                str(item['order_count'])
            ])
        
        cust_table = Table(cust_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        cust_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9b59b6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(cust_table)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


# ============= ENHANCED FINANCIAL EXCEL CONTENT =============

def generate_financial_excel_content(tenant, date_from, date_to):
    """Generate financial report as Excel with detailed breakdowns"""
    # Convert date strings to date objects
    try:
        from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except:
        from_date = timezone.now().date().replace(day=1)
        to_date = timezone.now().date()
    
    from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
    to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))
    
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=from_datetime,
        sale_date__lte=to_datetime
    )
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    # Define formats
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1,
        'font_size': 11,
    })
    sub_header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#3498db',
        'color': 'white',
        'border': 1,
        'font_size': 10,
    })
    currency_format = workbook.add_format({
        'num_format': '#,##0.00',
        'border': 1,
        'font_size': 10,
    })
    text_format = workbook.add_format({
        'border': 1,
        'font_size': 10,
    })
    title_format = workbook.add_format({
        'bold': True,
        'font_size': 16,
        'font_color': '#2c3e50',
    })
    bold_format = workbook.add_format({
        'bold': True,
        'border': 1,
        'font_size': 10,
    })
    percent_format = workbook.add_format({
        'num_format': '0.0%',
        'border': 1,
        'font_size': 10,
    })
    date_format = workbook.add_format({
        'num_format': 'yyyy-mm-dd',
        'border': 1,
        'font_size': 10,
    })
    
    # ===== SHEET 1: SUMMARY =====
    summary = workbook.add_worksheet('Summary')
    summary.set_column('A:A', 25)
    summary.set_column('B:B', 20)
    summary.set_column('C:C', 15)
    
    # Title
    summary.merge_range('A1:C1', f'Financial Report - {tenant.name}', title_format)
    summary.merge_range('A2:C2', f'Period: {date_from} to {date_to}', text_format)
    summary.merge_range('A3:C3', f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', text_format)
    
    # Calculations
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_orders = sales.count()
    avg_order = total_revenue / total_orders if total_orders > 0 else 0
    
    cogs = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0
    
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue) if total_revenue > 0 else 0
    
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    outstanding = Sale.objects.filter(
        tenant=tenant,
        balance_due__gt=0
    ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    collection_rate = (total_paid / total_revenue) if total_revenue > 0 else 0
    
    # Summary data
    summary_data = [
        ['Metric', 'Value'],
        ['Total Revenue', total_revenue],
        ['Total Tax', total_tax],
        ['Total Discount', total_discount],
        ['Net Revenue', total_revenue - total_tax - total_discount],
        ['Cost of Goods Sold (COGS)', cogs],
        ['Gross Profit', gross_profit],
        ['Gross Margin', gross_margin],
        ['Total Orders', total_orders],
        ['Average Order Value', avg_order],
        ['Total Received', total_paid],
        ['Outstanding', outstanding],
        ['Collection Rate', collection_rate],
    ]
    
    row = 5
    for label, value in summary_data:
        summary.write(row, 0, label, bold_format)
        if isinstance(value, Decimal) or isinstance(value, float):
            if label in ['Gross Margin', 'Collection Rate']:
                summary.write(row, 1, value, percent_format)
            elif isinstance(value, int) and label in ['Total Orders']:
                summary.write(row, 1, value, text_format)
            else:
                summary.write(row, 1, value, currency_format)
        else:
            summary.write(row, 1, value, text_format)
        row += 1
    
    # ===== SHEET 2: REVENUE BY CATEGORY =====
    cat_sheet = workbook.add_worksheet('Revenue by Category')
    cat_sheet.set_column('A:A', 30)
    cat_sheet.set_column('B:B', 20)
    cat_sheet.set_column('C:C', 15)
    cat_sheet.set_column('D:D', 20)
    
    revenue_by_category = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__category__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity'),
        total_cost=Sum(F('quantity') * F('product__purchase_price'))
    ).order_by('-total_revenue'))
    
    headers = ['Category', 'Revenue', 'Quantity', 'Cost']
    for col, header in enumerate(headers):
        cat_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_category:
        cat_sheet.write(row, 0, item['product__category__name'] or 'Uncategorized', text_format)
        cat_sheet.write(row, 1, float(item['total_revenue'] or 0), currency_format)
        cat_sheet.write(row, 2, float(item['total_quantity'] or 0), text_format)
        cat_sheet.write(row, 3, float(item['total_cost'] or 0), currency_format)
        row += 1
    
    # Add total row
    if revenue_by_category:
        total_cat_revenue = sum(float(item['total_revenue'] or 0) for item in revenue_by_category)
        total_cat_qty = sum(float(item['total_quantity'] or 0) for item in revenue_by_category)
        total_cat_cost = sum(float(item['total_cost'] or 0) for item in revenue_by_category)
        
        cat_sheet.write(row, 0, 'TOTAL', bold_format)
        cat_sheet.write(row, 1, total_cat_revenue, currency_format)
        cat_sheet.write(row, 2, total_cat_qty, text_format)
        cat_sheet.write(row, 3, total_cat_cost, currency_format)
    
    # ===== SHEET 3: REVENUE BY PAYMENT METHOD =====
    pay_sheet = workbook.add_worksheet('Revenue by Payment')
    pay_sheet.set_column('A:A', 25)
    pay_sheet.set_column('B:B', 20)
    pay_sheet.set_column('C:C', 15)
    
    revenue_by_payment = list(Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    
    headers = ['Payment Method', 'Total', 'Count']
    for col, header in enumerate(headers):
        pay_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_payment:
        pay_sheet.write(row, 0, item['method'].replace('_', ' ').title(), text_format)
        pay_sheet.write(row, 1, float(item['total'] or 0), currency_format)
        pay_sheet.write(row, 2, item['count'], text_format)
        row += 1
    
    # ===== SHEET 4: TOP PRODUCTS =====
    prod_sheet = workbook.add_worksheet('Top Products')
    prod_sheet.set_column('A:A', 30)
    prod_sheet.set_column('B:B', 20)
    prod_sheet.set_column('C:C', 15)
    prod_sheet.set_column('D:D', 20)
    
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__name', 'product__sku').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue')[:50])
    
    headers = ['Product Name', 'SKU', 'Revenue', 'Quantity']
    for col, header in enumerate(headers):
        prod_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in top_products:
        prod_sheet.write(row, 0, item['product__name'] or 'Unknown', text_format)
        prod_sheet.write(row, 1, item['product__sku'] or '', text_format)
        prod_sheet.write(row, 2, float(item['total_revenue'] or 0), currency_format)
        prod_sheet.write(row, 3, float(item['total_quantity'] or 0), text_format)
        row += 1
    
    # ===== SHEET 5: TOP CUSTOMERS =====
    cust_sheet = workbook.add_worksheet('Top Customers')
    cust_sheet.set_column('A:A', 30)
    cust_sheet.set_column('B:B', 20)
    cust_sheet.set_column('C:C', 15)
    
    top_customers = list(sales.values('customer_name').annotate(
        total_spent=Sum('total_amount'),
        order_count=Count('id')
    ).filter(customer_name__isnull=False).exclude(customer_name='').order_by('-total_spent')[:50])
    
    headers = ['Customer Name', 'Total Spent', 'Order Count']
    for col, header in enumerate(headers):
        cust_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in top_customers:
        cust_sheet.write(row, 0, item['customer_name'], text_format)
        cust_sheet.write(row, 1, float(item['total_spent'] or 0), currency_format)
        cust_sheet.write(row, 2, item['order_count'], text_format)
        row += 1
    
    # ===== SHEET 6: DAILY SALES =====
    daily_sheet = workbook.add_worksheet('Daily Sales')
    daily_sheet.set_column('A:A', 15)
    daily_sheet.set_column('B:B', 20)
    daily_sheet.set_column('C:C', 15)
    daily_sheet.set_column('D:D', 15)
    daily_sheet.set_column('E:E', 15)
    
    from django.db.models.functions import TruncDate
    revenue_by_day = list(sales.annotate(
        date=TruncDate('sale_date')
    ).values('date').annotate(
        revenue=Sum('total_amount'),
        tax=Sum('tax_amount'),
        discount=Sum('discount_amount'),
        count=Count('id')
    ).order_by('date'))
    
    headers = ['Date', 'Revenue', 'Tax', 'Discount', 'Order Count']
    for col, header in enumerate(headers):
        daily_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_day:
        daily_sheet.write(row, 0, item['date'].strftime('%Y-%m-%d'), date_format)
        daily_sheet.write(row, 1, float(item['revenue'] or 0), currency_format)
        daily_sheet.write(row, 2, float(item['tax'] or 0), currency_format)
        daily_sheet.write(row, 3, float(item['discount'] or 0), currency_format)
        daily_sheet.write(row, 4, item['count'], text_format)
        row += 1
    
    workbook.close()
    output.seek(0)
    return output.getvalue()


# ============= EXCEL CONTENT GENERATION FUNCTIONS =============

def generate_sales_excel_content(tenant, date_from, date_to):
    """Generate sales report as Excel content (bytes)"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1
    })
    currency_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
    text_format = workbook.add_format({'border': 1})
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
    
    # Sales sheet
    worksheet = workbook.add_worksheet('Sales')
    
    headers = ['Invoice', 'Customer', 'Phone', 'Date', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 15)
    
    row = 1
    for sale in sales:
        worksheet.write(row, 0, sale.invoice_number, text_format)
        worksheet.write(row, 1, sale.customer_name or 'Walk-in', text_format)
        worksheet.write(row, 2, sale.customer_phone or '', text_format)
        worksheet.write(row, 3, sale.sale_date.strftime('%Y-%m-%d'), date_format)
        worksheet.write(row, 4, float(sale.subtotal), currency_format)
        worksheet.write(row, 5, float(sale.tax_amount), currency_format)
        worksheet.write(row, 6, float(sale.discount_amount), currency_format)
        worksheet.write(row, 7, float(sale.total_amount), currency_format)
        worksheet.write(row, 8, sale.get_payment_status_display(), text_format)
        row += 1
    
    # Summary sheet
    summary = workbook.add_worksheet('Summary')
    summary.write(0, 0, 'Metric', header_format)
    summary.write(0, 1, 'Value', header_format)
    summary.set_column(0, 0, 20)
    summary.set_column(1, 1, 20)
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    
    summary_data = [
        ('Total Sales', sales.count()),
        ('Total Revenue', float(total_revenue)),
        ('Total Tax', float(total_tax)),
        ('Total Discount', float(total_discount)),
        ('Average Sale', float(total_revenue/sales.count()) if sales.count() > 0 else 0),
    ]
    
    for i, (label, value) in enumerate(summary_data, 1):
        summary.write(i, 0, label, text_format)
        if isinstance(value, float):
            summary.write(i, 1, value, currency_format)
        else:
            summary.write(i, 1, value, text_format)
    
    workbook.close()
    output.seek(0)
    return output.getvalue()


def generate_inventory_excel_content(tenant):
    """Generate inventory report as Excel content (bytes)"""
    products = Product.objects.filter(tenant=tenant)
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1
    })
    currency_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
    text_format = workbook.add_format({'border': 1})
    
    worksheet = workbook.add_worksheet('Inventory')
    
    headers = ['Product', 'SKU', 'Category', 'Quantity', 'Purchase Price', 'Selling Price', 'Total Value', 'Status']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 15)
    
    row = 1
    for product in products:
        value = product.quantity * product.purchase_price
        worksheet.write(row, 0, product.name, text_format)
        worksheet.write(row, 1, product.sku, text_format)
        worksheet.write(row, 2, product.category.name if product.category else '', text_format)
        worksheet.write(row, 3, int(product.quantity), text_format)
        worksheet.write(row, 4, float(product.purchase_price), currency_format)
        worksheet.write(row, 5, float(product.selling_price), currency_format)
        worksheet.write(row, 6, float(value), currency_format)
        worksheet.write(row, 7, product.get_status_display(), text_format)
        row += 1
    
    workbook.close()
    output.seek(0)
    return output.getvalue()



# ============= CSV GENERATION FUNCTIONS =============

def generate_sales_csv(tenant, date_from, date_to):
    """Generate sales report as CSV"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    writer.writerow(['Invoice', 'Customer', 'Phone', 'Date', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status'])
    
    # Write data
    for sale in sales:
        writer.writerow([
            sale.invoice_number,
            sale.customer_name or 'Walk-in',
            sale.customer_phone or '',
            sale.sale_date.strftime('%Y-%m-%d'),
            float(sale.subtotal),
            float(sale.tax_amount),
            float(sale.discount_amount),
            float(sale.total_amount),
            sale.get_payment_status_display()
        ])
    
    return output.getvalue().encode('utf-8-sig')  # UTF-8 with BOM for Excel compatibility


def generate_inventory_csv(tenant):
    """Generate inventory report as CSV"""
    products = Product.objects.filter(tenant=tenant)
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write headers
    writer.writerow(['Product', 'SKU', 'Category', 'Quantity', 'Purchase Price', 'Selling Price', 'Total Value', 'Status'])
    
    # Write data
    for product in products:
        value = product.quantity * product.purchase_price
        writer.writerow([
            product.name,
            product.sku,
            product.category.name if product.category else '',
            int(product.quantity),
            float(product.purchase_price),
            float(product.selling_price),
            float(value),
            product.get_status_display()
        ])
    
    return output.getvalue().encode('utf-8-sig')


def generate_financial_csv(tenant, date_from, date_to):
    """Generate financial report as CSV"""
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__date__gte=date_from,
        sale_date__date__lte=date_to
    )
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write summary
    writer.writerow(['Financial Report Summary'])
    writer.writerow(['Period:', f'{date_from} to {date_to}'])
    writer.writerow([])
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    writer.writerow(['Metric', 'Amount'])
    writer.writerow(['Total Revenue', f'Ugx {total_revenue:,.2f}'])
    writer.writerow(['Total Tax', f'Ugx {total_tax:,.2f}'])
    writer.writerow(['Total Discount', f'Ugx {total_discount:,.2f}'])
    writer.writerow(['Total Paid', f'Ugx {total_paid:,.2f}'])
    writer.writerow(['Net Revenue', f'Ugx {(total_revenue - total_tax):,.2f}'])
    writer.writerow([])
    
    # Write sales details
    writer.writerow(['Sales Details'])
    writer.writerow(['Invoice', 'Customer', 'Date', 'Subtotal', 'Tax', 'Discount', 'Total'])
    
    for sale in sales:
        writer.writerow([
            sale.invoice_number,
            sale.customer_name or 'Walk-in',
            sale.sale_date.strftime('%Y-%m-%d'),
            float(sale.subtotal),
            float(sale.tax_amount),
            float(sale.discount_amount),
            float(sale.total_amount)
        ])
    
    return output.getvalue().encode('utf-8-sig')


# Keep the original export functions for backward compatibility (they use request)
# but they're no longer used for report generation

@login_required
def export_sales_pdf(request):
    """Export sales report as PDF (for direct download)"""
    tenant = request.user.tenant
    sales = get_filtered_sales(request, tenant)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    elements.append(Paragraph(f"Sales Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_count = sales.count()
    
    summary_data = [
        ['Total Sales', 'Total Revenue', 'Average Sale'],
        [str(total_count), f'Ugx {total_revenue:,.2f}', f'Ugx {(total_revenue/total_count):,.2f}' if total_count > 0 else 'Ugx 0.00']
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    table_data = [['Invoice', 'Customer', 'Date', 'Total', 'Status']]
    for sale in sales[:100]:
        table_data.append([
            sale.invoice_number,
            sale.customer_name or 'Walk-in',
            sale.sale_date.strftime('%Y-%m-%d'),
            f'Ugx {sale.total_amount:,.2f}',
            sale.get_payment_status_display()
        ])
    
    sales_table = Table(table_data, colWidths=[1.5*inch, 2*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    sales_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    elements.append(sales_table)
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="sales_report_{datetime.now().strftime("%Y%m%d")}.pdf"'
    return response


@login_required
def export_sales_excel(request):
    """Export sales report as Excel (for direct download)"""
    tenant = request.user.tenant
    sales = get_filtered_sales(request, tenant)
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1
    })
    currency_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
    text_format = workbook.add_format({'border': 1})
    date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'border': 1})
    
    worksheet = workbook.add_worksheet('Sales')
    
    headers = ['Invoice', 'Customer', 'Phone', 'Date', 'Subtotal', 'Tax', 'Discount', 'Total', 'Status']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 15)
    
    row = 1
    for sale in sales:
        worksheet.write(row, 0, sale.invoice_number, text_format)
        worksheet.write(row, 1, sale.customer_name or 'Walk-in', text_format)
        worksheet.write(row, 2, sale.customer_phone or '', text_format)
        worksheet.write(row, 3, sale.sale_date.strftime('%Y-%m-%d'), date_format)
        worksheet.write(row, 4, float(sale.subtotal), currency_format)
        worksheet.write(row, 5, float(sale.tax_amount), currency_format)
        worksheet.write(row, 6, float(sale.discount_amount), currency_format)
        worksheet.write(row, 7, float(sale.total_amount), currency_format)
        worksheet.write(row, 8, sale.get_payment_status_display(), text_format)
        row += 1
    
    workbook.close()
    output.seek(0)
    
    response = HttpResponse(
        output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="sales_report_{datetime.now().strftime("%Y%m%d")}.xlsx"'
    return response


def get_filtered_sales(request, tenant):
    """Get filtered sales based on request parameters"""
    sales = Sale.objects.filter(tenant=tenant)
    
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status = request.GET.get('status')
    payment_method = request.GET.get('payment_method')
    
    if date_from:
        sales = sales.filter(sale_date__date__gte=date_from)
    if date_to:
        sales = sales.filter(sale_date__date__lte=date_to)
    if status:
        sales = sales.filter(payment_status=status)
    if payment_method:
        sales = sales.filter(payment_method=payment_method)
    
    return sales


@login_required
def export_inventory_pdf(request):
    """Export inventory report as PDF (for direct download)"""
    tenant = request.user.tenant
    products = get_filtered_products(request, tenant)
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    elements.append(Paragraph(f"Inventory Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 20))
    
    total_value = products.aggregate(total=Sum(F('quantity') * F('purchase_price')))['total'] or 0
    total_quantity = products.aggregate(total=Sum('quantity'))['total'] or 0
    
    summary_data = [
        ['Total Products', 'Total Quantity', 'Total Value'],
        [str(products.count()), str(int(total_quantity)), f'Ugx {total_value:,.2f}']
    ]
    
    summary_table = Table(summary_data, colWidths=[2*inch, 2*inch, 2*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    table_data = [['Product', 'SKU', 'Quantity', 'Price', 'Value', 'Status']]
    for product in products[:100]:
        value = product.quantity * product.purchase_price
        table_data.append([
            product.name,
            product.sku,
            str(int(product.quantity)),
            f'Ugx {product.purchase_price:,.2f}',
            f'Ugx {value:,.2f}',
            product.get_status_display()
        ])
    
    product_table = Table(table_data, colWidths=[2*inch, 1.5*inch, 1*inch, 1.5*inch, 1.5*inch, 1.5*inch])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    elements.append(product_table)
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="inventory_report_{datetime.now().strftime("%Y%m%d")}.pdf"'
    return response


@login_required
def export_inventory_excel(request):
    """Export inventory report as Excel (for direct download)"""
    tenant = request.user.tenant
    products = get_filtered_products(request, tenant)
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1
    })
    currency_format = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
    text_format = workbook.add_format({'border': 1})
    
    worksheet = workbook.add_worksheet('Inventory')
    
    headers = ['Product', 'SKU', 'Category', 'Quantity', 'Purchase Price', 'Selling Price', 'Total Value', 'Status']
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)
        worksheet.set_column(col, col, 15)
    
    row = 1
    for product in products:
        value = product.quantity * product.purchase_price
        worksheet.write(row, 0, product.name, text_format)
        worksheet.write(row, 1, product.sku, text_format)
        worksheet.write(row, 2, product.category.name if product.category else '', text_format)
        worksheet.write(row, 3, int(product.quantity), text_format)
        worksheet.write(row, 4, float(product.purchase_price), currency_format)
        worksheet.write(row, 5, float(product.selling_price), currency_format)
        worksheet.write(row, 6, float(value), currency_format)
        worksheet.write(row, 7, product.get_status_display(), text_format)
        row += 1
    
    workbook.close()
    output.seek(0)
    
    response = HttpResponse(
        output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="inventory_report_{datetime.now().strftime("%Y%m%d")}.xlsx"'
    return response


def get_filtered_products(request, tenant):
    """Get filtered products based on request parameters"""
    products = Product.objects.filter(tenant=tenant)
    
    category = request.GET.get('category')
    status = request.GET.get('status')
    stock_filter = request.GET.get('stock_filter')
    
    if category:
        products = products.filter(category_id=category)
    if status:
        products = products.filter(status=status)
    if stock_filter == 'low':
        products = products.filter(quantity__lte=F('reorder_point'), quantity__gt=0)
    elif stock_filter == 'out':
        products = products.filter(quantity=0)
    elif stock_filter == 'in':
        products = products.filter(quantity__gt=0)
    
    return products

# ============= ENHANCED FINANCIAL EXPORT FUNCTIONS =============
# ============= ENHANCED FINANCIAL EXPORT FUNCTIONS =============

@login_required
def export_financial_pdf(request):
    """Export financial report as PDF with detailed breakdowns"""
    tenant = request.user.tenant
    
    # Get date parameters with proper defaults
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    selected_year = request.GET.get('year')
    selected_month = request.GET.get('month')
    
    # If date_from or date_to are empty strings, set them to None
    if date_from == '':
        date_from = None
    if date_to == '':
        date_to = None
    
    # Get earliest and latest sale dates for default "All" view
    earliest_sale = Sale.objects.filter(tenant=tenant).order_by('sale_date').first()
    latest_sale = Sale.objects.filter(tenant=tenant).order_by('-sale_date').first()
    
    # Default to ALL DATA if no date filters
    if not date_from and not date_to and not selected_year and not selected_month:
        if earliest_sale and latest_sale:
            date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
            date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            today = timezone.now().date()
            date_from = today.replace(day=1).isoformat()
            date_to = today.isoformat()
    elif not date_from and not date_to:
        if selected_year and selected_month:
            import calendar
            date_from = f"{selected_year}-{str(selected_month).zfill(2)}-01"
            last_day = calendar.monthrange(int(selected_year), int(selected_month))[1]
            date_to = f"{selected_year}-{str(selected_month).zfill(2)}-{last_day}"
        elif selected_year:
            date_from = f"{selected_year}-01-01"
            date_to = f"{selected_year}-12-31"
        else:
            # Fallback to all data
            if earliest_sale and latest_sale:
                date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
                date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
            else:
                today = timezone.now().date()
                date_from = today.replace(day=1).isoformat()
                date_to = today.isoformat()
    
    # Ensure date_from and date_to are set
    if not date_from:
        today = timezone.now().date()
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        today = timezone.now().date()
        date_to = today.isoformat()
    
    # Convert date strings to date objects
    try:
        from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except ValueError:
        today = timezone.now().date()
        from_date = today.replace(day=1)
        to_date = today
        date_from = from_date.isoformat()
        date_to = to_date.isoformat()
    
    from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
    to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))
    
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=from_datetime,
        sale_date__lte=to_datetime
    )
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    heading_style = ParagraphStyle(
        'Heading2',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=15
    )
    normal_style = styles['Normal']
    
    elements.append(Paragraph(f"Financial Report - {tenant.name}", title_style))
    elements.append(Paragraph(f"Period: {date_from} to {date_to}", normal_style))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", normal_style))
    elements.append(Spacer(1, 20))
    
    # ===== SUMMARY STATISTICS =====
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_orders = sales.count()
    avg_order = total_revenue / total_orders if total_orders > 0 else 0
    
    # COGS and Gross Profit
    cogs = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0
    
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue * 100) if total_revenue > 0 else 0
    
    # Payments
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    outstanding = Sale.objects.filter(
        tenant=tenant,
        balance_due__gt=0
    ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    collection_rate = (total_paid / total_revenue * 100) if total_revenue > 0 else 0
    
    elements.append(Paragraph("Financial Summary", heading_style))
    summary_data = [
        ['Metric', 'Amount'],
        ['Total Revenue', f'Ugx {total_revenue:,.2f}'],
        ['Total Tax', f'Ugx {total_tax:,.2f}'],
        ['Total Discount', f'Ugx {total_discount:,.2f}'],
        ['Net Revenue', f'Ugx {(total_revenue - total_tax - total_discount):,.2f}'],
        ['Cost of Goods Sold (COGS)', f'Ugx {cogs:,.2f}'],
        ['Gross Profit', f'Ugx {gross_profit:,.2f}'],
        ['Gross Margin', f'{gross_margin:.1f}%'],
        ['Total Orders', str(total_orders)],
        ['Average Order Value', f'Ugx {avg_order:,.2f}'],
        ['Total Received', f'Ugx {total_paid:,.2f}'],
        ['Outstanding', f'Ugx {outstanding:,.2f}'],
        ['Collection Rate', f'{collection_rate:.1f}%'],
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.5*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    # ===== REVENUE BY CATEGORY =====
    revenue_by_category = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__category__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue'))
    
    if revenue_by_category:
        elements.append(Paragraph("Revenue by Category", heading_style))
        cat_data = [['Category', 'Revenue', 'Quantity']]
        for item in revenue_by_category[:15]:
            cat_data.append([
                item['product__category__name'] or 'Uncategorized',
                f'Ugx {item["total_revenue"]:,.2f}',
                str(int(item['total_quantity'] or 0))
            ])
        
        cat_table = Table(cat_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(cat_table)
        elements.append(Spacer(1, 20))
    
    # ===== REVENUE BY PAYMENT METHOD =====
    revenue_by_payment = list(Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    
    if revenue_by_payment:
        elements.append(Paragraph("Revenue by Payment Method", heading_style))
        pay_data = [['Payment Method', 'Total', 'Count']]
        for item in revenue_by_payment:
            pay_data.append([
                item['method'].replace('_', ' ').title(),
                f'Ugx {item["total"]:,.2f}',
                str(item['count'])
            ])
        
        pay_table = Table(pay_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        pay_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2ecc71')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(pay_table)
        elements.append(Spacer(1, 20))
    
    # ===== TOP 10 PRODUCTS =====
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue')[:10])
    
    if top_products:
        elements.append(Paragraph("Top 10 Products", heading_style))
        prod_data = [['Product', 'Revenue', 'Quantity']]
        for item in top_products:
            prod_data.append([
                item['product__name'] or 'Unknown',
                f'Ugx {item["total_revenue"]:,.2f}',
                str(int(item['total_quantity'] or 0))
            ])
        
        prod_table = Table(prod_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        prod_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f39c12')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(prod_table)
        elements.append(Spacer(1, 20))
    
    # ===== TOP CUSTOMERS =====
    top_customers = list(sales.values('customer_name').annotate(
        total_spent=Sum('total_amount'),
        order_count=Count('id')
    ).filter(customer_name__isnull=False).exclude(customer_name='').order_by('-total_spent')[:10])
    
    if top_customers:
        elements.append(Paragraph("Top Customers", heading_style))
        cust_data = [['Customer', 'Total Spent', 'Orders']]
        for item in top_customers:
            cust_data.append([
                item['customer_name'],
                f'Ugx {item["total_spent"]:,.2f}',
                str(item['order_count'])
            ])
        
        cust_table = Table(cust_data, colWidths=[2.5*inch, 2*inch, 1.5*inch])
        cust_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#9b59b6')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'CENTER'),
        ]))
        elements.append(cust_table)
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="financial_report_{datetime.now().strftime("%Y%m%d")}.pdf"'
    return response


@login_required
def export_financial_excel(request):
    """Export financial report as Excel with detailed breakdowns"""
    tenant = request.user.tenant
    
    # Get date parameters with proper defaults
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    selected_year = request.GET.get('year')
    selected_month = request.GET.get('month')
    
    # If date_from or date_to are empty strings, set them to None
    if date_from == '':
        date_from = None
    if date_to == '':
        date_to = None
    
    # Get earliest and latest sale dates for default "All" view
    earliest_sale = Sale.objects.filter(tenant=tenant).order_by('sale_date').first()
    latest_sale = Sale.objects.filter(tenant=tenant).order_by('-sale_date').first()
    
    # Default to ALL DATA if no date filters
    if not date_from and not date_to and not selected_year and not selected_month:
        if earliest_sale and latest_sale:
            date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
            date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
        else:
            today = timezone.now().date()
            date_from = today.replace(day=1).isoformat()
            date_to = today.isoformat()
    elif not date_from and not date_to:
        if selected_year and selected_month:
            import calendar
            date_from = f"{selected_year}-{str(selected_month).zfill(2)}-01"
            last_day = calendar.monthrange(int(selected_year), int(selected_month))[1]
            date_to = f"{selected_year}-{str(selected_month).zfill(2)}-{last_day}"
        elif selected_year:
            date_from = f"{selected_year}-01-01"
            date_to = f"{selected_year}-12-31"
        else:
            # Fallback to all data
            if earliest_sale and latest_sale:
                date_from = earliest_sale.sale_date.strftime('%Y-%m-%d')
                date_to = latest_sale.sale_date.strftime('%Y-%m-%d')
            else:
                today = timezone.now().date()
                date_from = today.replace(day=1).isoformat()
                date_to = today.isoformat()
    
    # Ensure date_from and date_to are set
    if not date_from:
        today = timezone.now().date()
        date_from = today.replace(day=1).isoformat()
    if not date_to:
        today = timezone.now().date()
        date_to = today.isoformat()
    
    # Convert date strings to date objects
    try:
        from_date = datetime.strptime(date_from, '%Y-%m-%d').date()
        to_date = datetime.strptime(date_to, '%Y-%m-%d').date()
    except ValueError:
        today = timezone.now().date()
        from_date = today.replace(day=1)
        to_date = today
        date_from = from_date.isoformat()
        date_to = to_date.isoformat()
    
    from_datetime = timezone.make_aware(datetime.combine(from_date, datetime.min.time()))
    to_datetime = timezone.make_aware(datetime.combine(to_date, datetime.max.time()))
    
    sales = Sale.objects.filter(
        tenant=tenant,
        sale_date__gte=from_datetime,
        sale_date__lte=to_datetime
    )
    
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output)
    
    # Define formats
    header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#2c3e50',
        'color': 'white',
        'border': 1,
        'font_size': 11,
    })
    sub_header_format = workbook.add_format({
        'bold': True,
        'bg_color': '#3498db',
        'color': 'white',
        'border': 1,
        'font_size': 10,
    })
    currency_format = workbook.add_format({
        'num_format': '#,##0.00',
        'border': 1,
        'font_size': 10,
    })
    text_format = workbook.add_format({
        'border': 1,
        'font_size': 10,
    })
    title_format = workbook.add_format({
        'bold': True,
        'font_size': 16,
        'font_color': '#2c3e50',
    })
    bold_format = workbook.add_format({
        'bold': True,
        'border': 1,
        'font_size': 10,
    })
    percent_format = workbook.add_format({
        'num_format': '0.0%',
        'border': 1,
        'font_size': 10,
    })
    date_format = workbook.add_format({
        'num_format': 'yyyy-mm-dd',
        'border': 1,
        'font_size': 10,
    })
    
    # ===== SHEET 1: SUMMARY =====
    summary = workbook.add_worksheet('Summary')
    summary.set_column('A:A', 25)
    summary.set_column('B:B', 20)
    summary.set_column('C:C', 15)
    
    # Title
    summary.merge_range('A1:C1', f'Financial Report - {tenant.name}', title_format)
    summary.merge_range('A2:C2', f'Period: {date_from} to {date_to}', text_format)
    summary.merge_range('A3:C3', f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}', text_format)
    
    # Calculations
    total_revenue = sales.aggregate(total=Sum('total_amount'))['total'] or 0
    total_tax = sales.aggregate(total=Sum('tax_amount'))['total'] or 0
    total_discount = sales.aggregate(total=Sum('discount_amount'))['total'] or 0
    total_orders = sales.count()
    avg_order = total_revenue / total_orders if total_orders > 0 else 0
    
    cogs = SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).aggregate(
        total=Sum(F('quantity') * F('product__purchase_price'))
    )['total'] or 0
    
    gross_profit = total_revenue - cogs
    gross_margin = (gross_profit / total_revenue) if total_revenue > 0 else 0
    
    total_paid = Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).aggregate(total=Sum('amount'))['total'] or 0
    
    outstanding = Sale.objects.filter(
        tenant=tenant,
        balance_due__gt=0
    ).aggregate(total=Sum('balance_due'))['total'] or 0
    
    collection_rate = (total_paid / total_revenue) if total_revenue > 0 else 0
    
    # Summary data
    summary_data = [
        ['Metric', 'Value'],
        ['Total Revenue', total_revenue],
        ['Total Tax', total_tax],
        ['Total Discount', total_discount],
        ['Net Revenue', total_revenue - total_tax - total_discount],
        ['Cost of Goods Sold (COGS)', cogs],
        ['Gross Profit', gross_profit],
        ['Gross Margin', gross_margin],
        ['Total Orders', total_orders],
        ['Average Order Value', avg_order],
        ['Total Received', total_paid],
        ['Outstanding', outstanding],
        ['Collection Rate', collection_rate],
    ]
    
    row = 5
    for label, value in summary_data:
        summary.write(row, 0, label, bold_format)
        if isinstance(value, Decimal) or isinstance(value, float):
            if label in ['Gross Margin', 'Collection Rate']:
                summary.write(row, 1, value, percent_format)
            elif isinstance(value, int) and label in ['Total Orders']:
                summary.write(row, 1, value, text_format)
            else:
                summary.write(row, 1, value, currency_format)
        else:
            summary.write(row, 1, value, text_format)
        row += 1
    
    # ===== SHEET 2: REVENUE BY CATEGORY =====
    cat_sheet = workbook.add_worksheet('Revenue by Category')
    cat_sheet.set_column('A:A', 30)
    cat_sheet.set_column('B:B', 20)
    cat_sheet.set_column('C:C', 15)
    cat_sheet.set_column('D:D', 20)
    
    revenue_by_category = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__category__name').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity'),
        total_cost=Sum(F('quantity') * F('product__purchase_price'))
    ).order_by('-total_revenue'))
    
    headers = ['Category', 'Revenue', 'Quantity', 'Cost']
    for col, header in enumerate(headers):
        cat_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_category:
        cat_sheet.write(row, 0, item['product__category__name'] or 'Uncategorized', text_format)
        cat_sheet.write(row, 1, float(item['total_revenue'] or 0), currency_format)
        cat_sheet.write(row, 2, float(item['total_quantity'] or 0), text_format)
        cat_sheet.write(row, 3, float(item['total_cost'] or 0), currency_format)
        row += 1
    
    # Add total row
    if revenue_by_category:
        total_cat_revenue = sum(float(item['total_revenue'] or 0) for item in revenue_by_category)
        total_cat_qty = sum(float(item['total_quantity'] or 0) for item in revenue_by_category)
        total_cat_cost = sum(float(item['total_cost'] or 0) for item in revenue_by_category)
        
        cat_sheet.write(row, 0, 'TOTAL', bold_format)
        cat_sheet.write(row, 1, total_cat_revenue, currency_format)
        cat_sheet.write(row, 2, total_cat_qty, text_format)
        cat_sheet.write(row, 3, total_cat_cost, currency_format)
    
    # ===== SHEET 3: REVENUE BY PAYMENT METHOD =====
    pay_sheet = workbook.add_worksheet('Revenue by Payment')
    pay_sheet.set_column('A:A', 25)
    pay_sheet.set_column('B:B', 20)
    pay_sheet.set_column('C:C', 15)
    
    revenue_by_payment = list(Payment.objects.filter(
        tenant=tenant,
        created_at__date__gte=from_date,
        created_at__date__lte=to_date
    ).values('method').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total'))
    
    headers = ['Payment Method', 'Total', 'Count']
    for col, header in enumerate(headers):
        pay_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_payment:
        pay_sheet.write(row, 0, item['method'].replace('_', ' ').title(), text_format)
        pay_sheet.write(row, 1, float(item['total'] or 0), currency_format)
        pay_sheet.write(row, 2, item['count'], text_format)
        row += 1
    
    # ===== SHEET 4: TOP PRODUCTS =====
    prod_sheet = workbook.add_worksheet('Top Products')
    prod_sheet.set_column('A:A', 30)
    prod_sheet.set_column('B:B', 20)
    prod_sheet.set_column('C:C', 15)
    prod_sheet.set_column('D:D', 20)
    
    top_products = list(SaleItem.objects.filter(
        sale__tenant=tenant,
        sale__sale_date__gte=from_datetime,
        sale__sale_date__lte=to_datetime
    ).values('product__name', 'product__sku').annotate(
        total_revenue=Sum('total_price'),
        total_quantity=Sum('quantity')
    ).order_by('-total_revenue')[:50])
    
    headers = ['Product Name', 'SKU', 'Revenue', 'Quantity']
    for col, header in enumerate(headers):
        prod_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in top_products:
        prod_sheet.write(row, 0, item['product__name'] or 'Unknown', text_format)
        prod_sheet.write(row, 1, item['product__sku'] or '', text_format)
        prod_sheet.write(row, 2, float(item['total_revenue'] or 0), currency_format)
        prod_sheet.write(row, 3, float(item['total_quantity'] or 0), text_format)
        row += 1
    
    # ===== SHEET 5: TOP CUSTOMERS =====
    cust_sheet = workbook.add_worksheet('Top Customers')
    cust_sheet.set_column('A:A', 30)
    cust_sheet.set_column('B:B', 20)
    cust_sheet.set_column('C:C', 15)
    
    top_customers = list(sales.values('customer_name').annotate(
        total_spent=Sum('total_amount'),
        order_count=Count('id')
    ).filter(customer_name__isnull=False).exclude(customer_name='').order_by('-total_spent')[:50])
    
    headers = ['Customer Name', 'Total Spent', 'Order Count']
    for col, header in enumerate(headers):
        cust_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in top_customers:
        cust_sheet.write(row, 0, item['customer_name'], text_format)
        cust_sheet.write(row, 1, float(item['total_spent'] or 0), currency_format)
        cust_sheet.write(row, 2, item['order_count'], text_format)
        row += 1
    
    # ===== SHEET 6: DAILY SALES =====
    daily_sheet = workbook.add_worksheet('Daily Sales')
    daily_sheet.set_column('A:A', 15)
    daily_sheet.set_column('B:B', 20)
    daily_sheet.set_column('C:C', 15)
    daily_sheet.set_column('D:D', 15)
    daily_sheet.set_column('E:E', 15)
    
    from django.db.models.functions import TruncDate
    revenue_by_day = list(sales.annotate(
        date=TruncDate('sale_date')
    ).values('date').annotate(
        revenue=Sum('total_amount'),
        tax=Sum('tax_amount'),
        discount=Sum('discount_amount'),
        count=Count('id')
    ).order_by('date'))
    
    headers = ['Date', 'Revenue', 'Tax', 'Discount', 'Order Count']
    for col, header in enumerate(headers):
        daily_sheet.write(0, col, header, sub_header_format)
    
    row = 1
    for item in revenue_by_day:
        daily_sheet.write(row, 0, item['date'].strftime('%Y-%m-%d'), date_format)
        daily_sheet.write(row, 1, float(item['revenue'] or 0), currency_format)
        daily_sheet.write(row, 2, float(item['tax'] or 0), currency_format)
        daily_sheet.write(row, 3, float(item['discount'] or 0), currency_format)
        daily_sheet.write(row, 4, item['count'], text_format)
        row += 1
    
    workbook.close()
    output.seek(0)
    
    response = HttpResponse(
        output,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="financial_report_{datetime.now().strftime("%Y%m%d")}.xlsx"'
    return response