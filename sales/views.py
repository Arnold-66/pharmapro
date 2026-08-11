# apps/sales/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q, Sum, Count, F
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
import datetime
import logging

from .models import Sale, SaleItem, Payment
from inventory.models import Product, StockMovement

logger = logging.getLogger(__name__)


def user_can_view_sales(user):
    """Check if user can view sales"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'staff', 'viewer'])


def user_can_manage_sales(user):
    """Check if user can manage sales (create)"""
    return user.is_authenticated and (user.is_superuser or user.role in ['admin', 'manager', 'staff'])


@login_required
def dashboard_view(request):
    """Sales dashboard - filtered by user for staff and viewers"""
    if not user_can_view_sales(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    sales_qs = Sale.objects.filter(tenant=tenant)

    # Staff and viewers only see their own sales
    if request.user.role in ['staff', 'viewer']:
        sales_qs = sales_qs.filter(created_by=request.user)
        recent_sales = sales_qs.order_by('-sale_date')[:10]
    else:
        recent_sales = sales_qs.order_by('-sale_date')[:10]

    total_sales = sales_qs.count()
    total_revenue = sales_qs.aggregate(total=Sum('total_amount'))['total'] or 0
    total_paid = sales_qs.filter(payment_status='paid').count()

    sales_by_status = sales_qs.values('payment_status').annotate(count=Count('id'))

    today = timezone.now().date()
    today_sales = sales_qs.filter(
        sale_date__date=today
    ).aggregate(
        total=Sum('total_amount'),
        count=Count('id')
    )

    from django.db.models.functions import TruncMonth
    monthly_sales = sales_qs.annotate(
        month=TruncMonth('sale_date')
    ).values('month').annotate(
        total=Sum('total_amount')
    ).order_by('month')

    context = {
        'total_sales': total_sales,
        'total_revenue': total_revenue,
        'total_paid': total_paid,
        'recent_sales': recent_sales,
        'sales_by_status': sales_by_status,
        'today_sales': today_sales['total'] or 0,
        'today_count': today_sales['count'] or 0,
        'monthly_sales': list(monthly_sales),
        'can_manage': user_can_manage_sales(request.user),
        'title': 'Sales Dashboard - PharmaPro'
    }
    return render(request, 'sales/dashboard.html', context)


@login_required
def sale_list_view(request):
    """List all sales - filtered by user for staff and viewers"""
    if not user_can_view_sales(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    sales = Sale.objects.filter(tenant=tenant)

    # Staff and viewers only see their own sales
    if request.user.role in ['staff', 'viewer']:
        sales = sales.filter(created_by=request.user)

    search_query = request.GET.get('search', '')
    if search_query:
        sales = sales.filter(
            Q(invoice_number__icontains=search_query) |
            Q(customer_name__icontains=search_query) |
            Q(customer_phone__icontains=search_query)
        )

    status_filter = request.GET.get('status', '')
    if status_filter:
        sales = sales.filter(payment_status=status_filter)

    date_from = request.GET.get('date_from', '')
    if date_from:
        sales = sales.filter(sale_date__date__gte=date_from)

    date_to = request.GET.get('date_to', '')
    if date_to:
        sales = sales.filter(sale_date__date__lte=date_to)

    sales = sales.order_by('-sale_date')

    paginator = Paginator(sales, 20)
    page_number = request.GET.get('page', 1)
    sales_page = paginator.get_page(page_number)

    for sale in sales_page:
        sale.is_overpaid = sale.balance_due < 0
        sale.balance_display = abs(sale.balance_due)
        sale.change_display = sale.change_amount

    context = {
        'sales': sales_page,
        'search_query': search_query,
        'status_filter': status_filter,
        'date_from': date_from,
        'date_to': date_to,
        'can_manage': user_can_manage_sales(request.user),
        'title': 'Sales - PharmaPro'
    }
    return render(request, 'sales/list.html', context)


@login_required
def sale_create_view(request):
    """Create a new sale - staff and above can create"""
    if not user_can_manage_sales(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant

    # ===== FIX: Get tax rate from TenantSettings =====
    from tenants.models import TenantSettings
    from decimal import Decimal

    try:
        settings_obj = TenantSettings.objects.get(tenant=tenant)
        tax_rate_from_settings = float(settings_obj.tax_rate)
        print(f"=== TAX RATE FROM SETTINGS: {tax_rate_from_settings} ===")  # Debug
    except TenantSettings.DoesNotExist:
        tax_rate_from_settings = 18.00
        print("=== NO SETTINGS FOUND, USING DEFAULT 18 ===")
    except Exception as e:
        tax_rate_from_settings = 18.00
        print(f"=== ERROR GETTING TAX RATE: {e} ===")
        logger.error(f"Error getting tax settings: {e}")

    if request.method == 'POST':
        try:
            with transaction.atomic():
                # Get tax rate from POST or use settings
                tax_rate = Decimal(request.POST.get('tax_rate', str(tax_rate_from_settings)))
                tax_rate_decimal = tax_rate / Decimal('100')

                amount_received = Decimal(request.POST.get('amount_received', '0'))
                payment_method = request.POST.get('payment_method', 'cash')

                import uuid
                import datetime
                today = datetime.date.today().strftime('%Y%m%d')
                random_suffix = str(uuid.uuid4().hex[:6].upper())
                invoice_number = f"INV-{today}-{random_suffix}"

                while Sale.objects.filter(invoice_number=invoice_number).exists():
                    random_suffix = str(uuid.uuid4().hex[:6].upper())
                    invoice_number = f"INV-{today}-{random_suffix}"

                sale = Sale.objects.create(
                    tenant=tenant,
                    invoice_number=invoice_number,
                    customer_name=request.POST.get('customer_name', '').strip() or 'Walk-in Customer',
                    customer_phone=request.POST.get('customer_phone', '').strip(),
                    due_date=request.POST.get('due_date') or timezone.now().date() + timezone.timedelta(days=30),
                    shipping_address=request.POST.get('shipping_address', ''),
                    notes=request.POST.get('notes', ''),
                    tax_rate=tax_rate,
                    payment_method=payment_method,
                    created_by=request.user
                )

                product_ids = request.POST.getlist('product_ids[]')
                unit_names = request.POST.getlist('unit_names[]')
                quantities = request.POST.getlist('quantities[]')
                unit_prices = request.POST.getlist('unit_prices[]')
                discounts = request.POST.getlist('discounts[]')

                subtotal = Decimal('0')
                tax_amount = Decimal('0')
                discount_amount = Decimal('0')

                for i in range(len(product_ids)):
                    if not product_ids[i]:
                        continue

                    product = get_object_or_404(Product, id=product_ids[i], tenant=tenant)
                    unit_name = unit_names[i] if i < len(unit_names) else ''
                    quantity = Decimal(quantities[i] or '0')
                    unit_price = Decimal(unit_prices[i] or '0')
                    discount = Decimal(discounts[i] or '0')

                    if quantity <= 0:
                        continue

                    sale_unit = product.sale_units.filter(name__iexact=unit_name).first()
                    if not sale_unit:
                        sale_unit = product.get_default_sale_unit()

                    if sale_unit:
                        multiplier = sale_unit.quantity_per_unit
                        actual_quantity = quantity * multiplier
                        unit_display_name = sale_unit.name
                    else:
                        actual_quantity = quantity
                        multiplier = 1
                        unit_display_name = product.unit.name if product.unit else 'units'

                    if product.quantity < actual_quantity:
                        messages.error(
                            request,
                            f'Insufficient stock for {product.name}. '
                            f'Available: {product.quantity} {product.unit.abbreviation if product.unit else "units"}, '
                            f'Required: {actual_quantity} base units for {quantity} {unit_display_name}(s)'
                        )
                        return redirect('sales:sale_create')

                    total_price = quantity * unit_price - discount
                    tax = total_price * tax_rate_decimal

                    SaleItem.objects.create(
                        sale=sale,
                        product=product,
                        quantity=quantity,
                        unit_price=unit_price,
                        total_price=total_price,
                        discount=discount,
                        tax=tax,
                        notes=f"{quantity} {unit_display_name}(s) ({actual_quantity} base units)"
                    )

                    previous_quantity = product.quantity
                    product.quantity -= actual_quantity
                    product.save()

                    StockMovement.objects.create(
                        tenant=tenant,
                        product=product,
                        movement_type='sale',
                        quantity=actual_quantity,
                        previous_quantity=previous_quantity,
                        new_quantity=product.quantity,
                        unit_price=unit_price,
                        total_price=total_price,
                        reference=sale.invoice_number,
                        notes=f'Sale #{sale.invoice_number} - {quantity} {unit_display_name}(s) (Base units: {actual_quantity})',
                        sale_unit_name=unit_display_name,
                        sale_quantity=quantity,
                        created_by=request.user
                    )

                    subtotal += quantity * unit_price
                    discount_amount += discount
                    tax_amount += tax

                total_amount = subtotal - discount_amount + tax_amount

                sale.subtotal = subtotal
                sale.tax_amount = tax_amount
                sale.discount_amount = discount_amount
                sale.total_amount = total_amount
                sale.balance_due = total_amount
                sale.change_amount = Decimal('0')
                sale.save()

                change_amount = Decimal('0')
                if amount_received > 0:
                    payment_amount = amount_received

                    if amount_received > total_amount:
                        change_amount = amount_received - total_amount
                    else:
                        change_amount = Decimal('0')

                    Payment.objects.create(
                        tenant=tenant,
                        sale=sale,
                        amount=payment_amount,
                        method=payment_method,
                        payer_name=request.POST.get('customer_name', '').strip() or 'Walk-in Customer',
                        notes=f'Amount received: {amount_received}, Change: {change_amount}',
                        created_by=request.user
                    )

                    sale.paid_amount = payment_amount
                    sale.balance_due = total_amount - payment_amount
                    sale.change_amount = change_amount
                    sale.update_payment_status()
                    sale.save()

                if change_amount > 0:
                    messages.success(
                        request,
                        f'Sale #{sale.invoice_number} created! 💰 Change to return: Ugx {change_amount:.2f}'
                    )
                elif change_amount == 0 and amount_received > 0:
                    messages.success(
                        request,
                        f'Sale #{sale.invoice_number} created successfully! ✅ Exact payment received.'
                    )
                elif amount_received == 0:
                    messages.warning(
                        request,
                        f'Sale #{sale.invoice_number} created! ⚠️ No payment received. Balance due: Ugx {total_amount:.2f}'
                    )
                else:
                    messages.warning(
                        request,
                        f'Sale #{sale.invoice_number} created! ⚠️ Balance due: Ugx {abs(sale.balance_due):.2f}'
                    )

                return redirect('sales:sale_receipt', sale_id=sale.id)

        except Exception as e:
            messages.error(request, f'Error creating sale: {str(e)}')
            logger.error(f"Sale creation error: {str(e)}")
            return redirect('sales:sale_create')

    # Get products for the form
    products = Product.objects.filter(tenant=tenant, is_active=True, quantity__gt=0)

    context = {
        'products': products,
        'default_tax_rate': tax_rate_from_settings,  # Use the settings value
        'title': 'Create Sale - PharmaPro'
    }
    return render(request, 'sales/create.html', context)



@login_required
def search_products(request):
    """Search products for sale creation - only for users who can create sales"""
    if not user_can_manage_sales(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    tenant = request.user.tenant
    query = request.GET.get('q', '').strip()

    if not query:
        return JsonResponse({'products': []})

    products = Product.objects.filter(
        tenant=tenant,
        is_active=True,
        quantity__gt=0
    ).filter(
        Q(name__icontains=query) |
        Q(barcode__icontains=query) |
        Q(sku__icontains=query)
    )[:20]

    data = []
    for product in products:
        stock = float(product.quantity)
        unit_name = product.unit.abbreviation if product.unit else 'units'

        data.append({
            'id': str(product.id),
            'name': product.name,
            'barcode': product.barcode or '',
            'stock': stock,
            'unit': unit_name,
        })

    return JsonResponse({'products': data})


@login_required
def sale_detail_view(request, sale_id):
    """View sale details - staff and viewers can only view their own sales"""
    if not user_can_view_sales(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    sale = get_object_or_404(Sale, id=sale_id, tenant=tenant)

    # Staff and viewers can only view their own sales
    if request.user.role in ['staff', 'viewer'] and sale.created_by != request.user:
        messages.error(request, 'You do not have permission to view this sale.')
        return redirect('sales:sale_list')

    items = sale.items.all().select_related('product')
    payments = sale.payments.all()

    total_items = items.count()
    total_quantity = items.aggregate(total=Sum('quantity'))['total'] or 0

    is_overpaid = sale.balance_due < 0
    is_fully_paid = sale.balance_due <= 0
    is_partial = sale.balance_due > 0 and sale.paid_amount > 0

    context = {
        'sale': sale,
        'items': items,
        'payments': payments,
        'total_items': total_items,
        'total_quantity': total_quantity,
        'change_amount': sale.change_amount,
        'balance_display': abs(sale.balance_due),
        'is_overpaid': is_overpaid,
        'is_fully_paid': is_fully_paid,
        'is_partial': is_partial,
        'can_manage': user_can_manage_sales(request.user),
        'title': f'Sale #{sale.invoice_number} - PharmaPro'
    }
    return render(request, 'sales/detail.html', context)


# apps/sales/views.py - Add receipt view

# apps/sales/views.py - Add this view

@login_required
def sale_receipt_view(request, sale_id):
    """View sale receipt for printing - staff and viewers can only view their own sales"""
    if not user_can_view_sales(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})

    tenant = request.user.tenant
    sale = get_object_or_404(Sale, id=sale_id, tenant=tenant)

    # Staff and viewers can only view their own sales
    if request.user.role in ['staff', 'viewer'] and sale.created_by != request.user:
        messages.error(request, 'You do not have permission to view this sale.')
        return redirect('sales:sale_list')

    items = sale.items.all().select_related('product')
    payments = sale.payments.all()

    # Get tenant logo and company info
    tenant_logo = tenant.logo.url if tenant.logo else None
    company_name = tenant.company_name or tenant.name
    company_address = tenant.company_address or ''
    company_phone = tenant.company_phone or ''
    company_email = tenant.company_email or ''

    # Check if auto_print is requested (default is true)
    auto_print = request.GET.get('auto_print', 'true') != 'false'

    context = {
        'sale': sale,
        'items': items,
        'payments': payments,
        'tenant_logo': tenant_logo,
        'company_name': company_name,
        'company_address': company_address,
        'company_phone': company_phone,
        'company_email': company_email,
        'auto_print': auto_print,
        'title': f'Receipt #{sale.invoice_number} - PharmaPro'
    }
    return render(request, 'sales/receipt.html', context)



# Add this import at the top
from django.http import HttpResponse
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.lib.units import inch, cm
import os
from django.conf import settings

@login_required
def sale_receipt_pdf_view(request, sale_id):
    """Generate PDF receipt for download"""
    if not user_can_view_sales(request.user):
        return HttpResponse('Permission denied', status=403)

    tenant = request.user.tenant
    sale = get_object_or_404(Sale, id=sale_id, tenant=tenant)

    if request.user.role in ['staff', 'viewer'] and sale.created_by != request.user:
        messages.error(request, 'You do not have permission to view this sale.')
        return redirect('sales:sale_list')

    items = sale.items.all().select_related('product')
    payments = sale.payments.all()

    # Create PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                           topMargin=0.5*inch, bottomMargin=0.5*inch,
                           leftMargin=0.5*inch, rightMargin=0.5*inch)

    styles = getSampleStyleSheet()
    story = []

    # Custom styles for supermarket receipt look
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        textColor=colors.black,
        alignment=TA_CENTER,
        spaceAfter=4,
        fontName='Courier-Bold'
    )

    normal_style = ParagraphStyle(
        'NormalStyle',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier',
        alignment=TA_LEFT,
    )

    center_style = ParagraphStyle(
        'CenterStyle',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier',
        alignment=TA_CENTER,
    )

    right_style = ParagraphStyle(
        'RightStyle',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier',
        alignment=TA_RIGHT,
    )

    bold_style = ParagraphStyle(
        'BoldStyle',
        parent=styles['Normal'],
        fontSize=9,
        fontName='Courier-Bold',
    )

    # Company Header
    company_name = tenant.company_name or tenant.name
    story.append(Paragraph(company_name.upper(), title_style))

    if tenant.company_address:
        story.append(Paragraph(tenant.company_address, center_style))

    phone_email = []
    if tenant.company_phone:
        phone_email.append(f"Tel: {tenant.company_phone}")
    if tenant.company_email:
        phone_email.append(tenant.company_email)
    if phone_email:
        story.append(Paragraph(" | ".join(phone_email), center_style))

    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("SALES RECEIPT", ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Normal'],
        fontSize=11,
        fontName='Courier-Bold',
        alignment=TA_CENTER,
        spaceAfter=6,
    )))
    story.append(Spacer(1, 0.05*inch))

    # Meta info
    meta_data = [
        (f"Receipt #: {sale.invoice_number}", ''),
        (f"Date/Time: {sale.sale_date.strftime('%m/%d/%Y %I:%M %p')}", ''),
        (f"Customer: {sale.customer_name or 'WALK-IN'}", ''),
    ]
    if sale.customer_phone:
        meta_data.append((f"Phone: {sale.customer_phone}", ''))
    meta_data.append((f"Status: {sale.get_payment_status_display().upper()}", ''))
    meta_data.append((f"Payment: {sale.get_payment_method_display().upper()}", ''))

    for label, value in meta_data:
        story.append(Paragraph(label, normal_style))

    story.append(Spacer(1, 0.05*inch))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, dash=None))
    story.append(Spacer(1, 0.05*inch))

    # Items - Header
    item_headers = ['ITEM', 'QTY', 'PRICE', 'TOTAL']
    item_data = [item_headers]

    for item in items:
        name = item.product.name.upper()
        if len(name) > 25:
            name = name[:22] + '...'
        item_data.append([
            name,
            str(int(item.quantity)),
            f"Ugx {item.unit_price:,.0f}",
            f"Ugx {item.total_price:,.0f}"
        ])

    item_table = Table(item_data, colWidths=[2*inch, 0.7*inch, 1.2*inch, 1.3*inch])
    item_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('ALIGN', (2, 0), (3, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Courier-Bold'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(item_table)
    story.append(Spacer(1, 0.05*inch))

    # Totals
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, dash=None))
    story.append(Spacer(1, 0.05*inch))

    totals = [
        ('SUBTOTAL', f"Ugx {sale.subtotal:,.0f}"),
    ]
    if sale.discount_amount > 0:
        totals.append(('DISCOUNT', f"-Ugx {sale.discount_amount:,.0f}"))
    totals.append((f"TAX ({sale.tax_rate:.0f}%)", f"Ugx {sale.tax_amount:,.0f}"))
    totals.append(('TOTAL', f"Ugx {sale.total_amount:,.0f}"))
    if sale.paid_amount > 0:
        totals.append(('AMOUNT PAID', f"Ugx {sale.paid_amount:,.0f}"))
    if sale.change_amount > 0:
        totals.append(('CHANGE', f"Ugx {sale.change_amount:,.0f}"))
    if sale.balance_due > 0:
        totals.append(('BALANCE DUE', f"Ugx {sale.balance_due:,.0f}"))

    for label, value in totals:
        story.append(Paragraph(f"{label:<20} {value:>15}",
            ParagraphStyle('TotalRow', parent=styles['Normal'], fontSize=9, fontName='Courier-Bold' if label == 'TOTAL' or label == 'BALANCE DUE' else 'Courier')))

    story.append(Spacer(1, 0.05*inch))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, dash=None))

    # Payments
    if payments:
        story.append(Spacer(1, 0.05*inch))
        story.append(Paragraph("PAYMENT DETAILS",
            ParagraphStyle('PayTitle', parent=styles['Normal'], fontSize=9, fontName='Courier-Bold')))
        for payment in payments:
            story.append(Paragraph(f"{payment.get_method_display().upper()}  Ugx {payment.amount:,.0f}  {payment.created_at.strftime('%m/%d/%y %H:%M')}", normal_style))
        story.append(Spacer(1, 0.05*inch))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, dash=None))

    # Notes
    if sale.notes:
        story.append(Spacer(1, 0.05*inch))
        story.append(Paragraph(f"Notes: {sale.notes}", normal_style))
        story.append(Spacer(1, 0.05*inch))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.black, dash=None))

    # Footer
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph("THANK YOU FOR YOUR BUSINESS!", ParagraphStyle(
        'Thanks',
        parent=styles['Normal'],
        fontSize=10,
        fontName='Courier-Bold',
        alignment=TA_CENTER,
        spaceAfter=4,
    )))
    story.append(Paragraph(f"{company_name.upper()}", center_style))
    story.append(Paragraph("Returns accepted within 14 days with valid receipt", center_style))
    story.append(Paragraph("Powered by PharmaPro", center_style))
    story.append(Paragraph(f"Generated: {timezone.now().strftime('%m/%d/%Y %I:%M:%S %p')}",
        ParagraphStyle('Timestamp', parent=styles['Normal'], fontSize=7, fontName='Courier', alignment=TA_CENTER)))

    doc.build(story)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="receipt_{sale.invoice_number}.pdf"'
    return response