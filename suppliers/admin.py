# apps/suppliers/admin.py
from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Supplier, SupplierContact, SupplierProduct, 
    PurchaseOrder, PurchaseOrderItem, SupplierPayment
)


class SupplierContactInline(admin.TabularInline):
    model = SupplierContact
    extra = 1
    fields = ('name', 'position', 'email', 'phone', 'mobile', 'is_primary')


class SupplierProductInline(admin.TabularInline):
    model = SupplierProduct
    extra = 1
    fields = ('product', 'cost_price', 'min_order_quantity', 'lead_time_days', 'is_preferred')
    raw_id_fields = ('product',)


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 1
    fields = ('product', 'quantity', 'unit_price', 'total_price', 'received_quantity')
    raw_id_fields = ('product',)


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ('payment_number', 'supplier', 'amount', 'payment_date', 'payment_method', 'reference_number', 'created_at')
    list_filter = ('payment_method', 'payment_date', 'supplier')
    search_fields = ('payment_number', 'supplier__name', 'supplier__code', 'reference_number')
    readonly_fields = ('payment_number', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('tenant', 'supplier', 'payment_number', 'amount', 'payment_date', 'payment_method')
        }),
        ('Reference Details', {
            'fields': ('reference_number', 'purchase_order', 'notes')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.tenant:
            return qs.filter(tenant=request.user.tenant)
        return qs.none()
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'contact_person', 'email', 'phone', 'status', 'is_approved', 'balance_due', 'total_paid')
    list_filter = ('status', 'is_approved', 'supplier_type', 'country')
    search_fields = ('name', 'code', 'contact_person', 'email', 'phone', 'tax_id')
    readonly_fields = ('created_at', 'updated_at', 'verified_at')
    inlines = [SupplierContactInline, SupplierProductInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tenant', 'name', 'code', 'supplier_type', 'status')
        }),
        ('Contact Information', {
            'fields': ('contact_person', 'email', 'phone', 'alternative_phone', 'fax', 'website')
        }),
        ('Address', {
            'fields': ('address', 'city', 'state', 'country', 'postal_code')
        }),
        ('Business Details', {
            'fields': ('tax_id', 'registration_number', 'bank_name', 'bank_account')
        }),
        ('Financial Information', {
            'fields': ('payment_terms', 'payment_method', 'credit_limit', 'balance_due', 'total_paid', 'total_purchases')
        }),
        ('Categories Supplied', {
            'fields': ('categories',)
        }),
        ('Performance Metrics', {
            'fields': ('lead_time_days', 'quality_rating', 'reliability_score')
        }),
        ('Verification & Status', {
            'fields': ('is_approved', 'is_verified', 'verified_at', 'verified_by')
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.tenant:
            return qs.filter(tenant=request.user.tenant)
        return qs.none()
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = ('po_number', 'supplier', 'status', 'order_date', 'expected_delivery_date', 'total_amount')
    list_filter = ('status', 'order_date', 'expected_delivery_date')
    search_fields = ('po_number', 'supplier__name', 'supplier__code')
    readonly_fields = ('created_at', 'updated_at', 'approved_at')
    inlines = [PurchaseOrderItemInline]
    
    fieldsets = (
        ('Order Information', {
            'fields': ('tenant', 'po_number', 'supplier', 'status')
        }),
        ('Dates', {
            'fields': ('order_date', 'expected_delivery_date', 'actual_delivery_date')
        }),
        ('Financials', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'shipping_cost', 'total_amount')
        }),
        ('Approvals', {
            'fields': ('approved_by', 'approved_at')
        }),
        ('Notes', {
            'fields': ('notes', 'internal_notes')
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.tenant:
            return qs.filter(tenant=request.user.tenant)
        return qs.none()
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)