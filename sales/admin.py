# apps/sales/admin.py

from django.contrib import admin
from django.db.models import Sum
from .models import Sale, SaleItem, Payment


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ['total_price']
    fields = ['product', 'quantity', 'unit_price', 'discount', 'tax', 'total_price']


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1
    readonly_fields = ['created_at']
    fields = ['amount', 'method', 'payer_name', 'reference', 'notes', 'created_at']


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'customer_name', 'sale_date', 'total_amount', 
        'paid_amount', 'balance_due', 'payment_status', 'delivery_status'
    ]
    list_filter = ['payment_status', 'delivery_status', 'payment_method', 'sale_date', 'tenant']
    search_fields = ['invoice_number', 'customer_name', 'customer_phone']
    readonly_fields = ['id', 'invoice_number', 'subtotal', 'tax_amount', 'total_amount', 'balance_due', 'created_at', 'updated_at']
    
    inlines = [SaleItemInline, PaymentInline]
    
    fieldsets = (
        ('Sale Information', {
            'fields': ('tenant', 'invoice_number', 'sale_date', 'due_date')
        }),
        ('Customer Information', {
            'fields': ('customer_name', 'customer_phone')
        }),
        ('Financial', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total_amount', 'paid_amount', 'balance_due')
        }),
        ('Payment', {
            'fields': ('payment_status', 'payment_method', 'payment_date')
        }),
        ('Delivery', {
            'fields': ('shipping_address', 'delivery_status', 'tracking_number')
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes')
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            if not obj.invoice_number:
                import datetime
                year = datetime.datetime.now().year
                count = Sale.objects.filter(tenant=obj.tenant, sale_date__year=year).count() + 1
                obj.invoice_number = f"INV-{year}-{str(count).zfill(6)}"
        super().save_model(request, obj, form, change)


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = ['sale', 'product', 'quantity', 'unit_price', 'total_price']
    list_filter = ['sale__tenant']
    search_fields = ['sale__invoice_number', 'product__name']
    readonly_fields = ['id', 'total_price', 'created_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sale', 'product')


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['sale', 'amount', 'method', 'payer_name', 'reference', 'created_at']
    list_filter = ['method', 'sale__tenant']
    search_fields = ['sale__invoice_number', 'payer_name', 'reference']
    readonly_fields = ['id', 'created_at']
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


admin.site.site_header = 'PharmaPro Administration'
admin.site.site_title = 'PharmaPro Admin'
admin.site.index_title = 'Welcome to PharmaPro Admin Panel'