# apps/inventory/admin.py - Add SaleUnitAdmin

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count, Sum
from .models import Category, Unit, Product, SaleUnit, StockMovement, InventoryAlert


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'tenant', 'get_full_path', 'is_active', 'product_count', 'created_at']
    list_filter = ['tenant', 'is_active', 'parent']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    list_editable = ['is_active']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'parent', 'tenant')
        }),
        ('Visual', {
            'fields': ('icon', 'color'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_full_path(self, obj):
        return obj.get_full_path()
    get_full_path.short_description = 'Path'
    
    def product_count(self, obj):
        return obj.get_products_count()
    product_count.short_description = 'Total Products'


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['name', 'abbreviation', 'tenant', 'created_at']
    list_filter = ['tenant']
    search_fields = ['name', 'abbreviation']
    readonly_fields = ['id', 'created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'abbreviation', 'tenant')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(SaleUnit)
class SaleUnitAdmin(admin.ModelAdmin):
    list_display = ['product', 'name', 'abbreviation', 'quantity_per_unit', 'selling_price', 'is_default', 'is_active']
    list_filter = ['tenant', 'is_default', 'is_active', 'product']
    search_fields = ['product__name', 'name', 'abbreviation']
    readonly_fields = ['id', 'created_at', 'updated_at']
    list_editable = ['selling_price', 'is_default', 'is_active']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tenant', 'product', 'name', 'abbreviation')
        }),
        ('Pricing & Quantity', {
            'fields': ('quantity_per_unit', 'selling_price', 'purchase_price')
        }),
        ('Status', {
            'fields': ('is_default', 'is_active')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'tenant')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'product_image', 'name', 'sku', 'category', 'unit',
        'quantity_display', 'selling_price', 'status', 'is_low_stock_display'
    ]
    list_filter = ['tenant', 'category', 'unit', 'status', 'is_featured']
    search_fields = ['name', 'sku', 'barcode', 'description', 'batch_number']
    readonly_fields = ['id', 'created_at', 'updated_at', 'total_value']
    list_editable = ['selling_price', 'status']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('tenant', 'name', 'sku', 'barcode', 'description', 'category', 'unit')
        }),
        ('Stock Information', {
            'fields': ('quantity', 'min_quantity', 'max_quantity', 'reorder_point', 'reorder_quantity')
        }),
        ('Pricing', {
            'fields': ('purchase_price', 'selling_price', 'wholesale_price', 'discount_price')
        }),
        ('Sale Units', {
            'fields': ('allow_fractional',),
            'classes': ('collapse',)
        }),
        ('Expiry & Tracking', {
            'fields': ('batch_number', 'expiry_date', 'manufacturing_date', 'location', 'shelf_number'),
            'classes': ('collapse',)
        }),
        ('Images', {
            'fields': ('image', 'gallery_images'),
            'classes': ('collapse',)
        }),
        ('Status & Visibility', {
            'fields': ('status', 'is_featured', 'is_active')
        }),
        ('Additional Details', {
            'fields': ('weight', 'dimensions'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def product_image(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;" />',
                obj.image.url
            )
        return '<span style="color: #999; font-size: 12px;">No image</span>'
    product_image.short_description = 'Image'
    product_image.allow_tags = True
    
    def quantity_display(self, obj):
        if obj.quantity <= 0:
            color = '#dc3545'
        elif obj.quantity <= obj.reorder_point:
            color = '#ffc107'
        else:
            color = '#28a745'
        unit_abbr = obj.unit.abbreviation if obj.unit else ''
        quantity = float(obj.quantity) if obj.quantity else 0
        return f'<span style="color: {color}; font-weight: bold;">{quantity} {unit_abbr}</span>'
    quantity_display.short_description = 'Quantity'
    quantity_display.allow_tags = True
    
    def is_low_stock_display(self, obj):
        if obj.quantity <= 0:
            return '<span style="color: #dc3545;">❌ Out of Stock</span>'
        elif obj.quantity <= obj.reorder_point:
            return '<span style="color: #ffc107;">⚠️ Low Stock</span>'
        else:
            return '<span style="color: #28a745;">✅ In Stock</span>'
    is_low_stock_display.short_description = 'Stock Status'
    is_low_stock_display.allow_tags = True
    
    def total_value(self, obj):
        return obj.quantity * obj.purchase_price
    total_value.short_description = 'Total Value'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('category', 'unit', 'tenant')
    
    actions = ['mark_active', 'mark_inactive', 'mark_out_of_stock']
    
    def mark_active(self, request, queryset):
        queryset.update(status='active', is_active=True)
    mark_active.short_description = "Mark selected products as Active"
    
    def mark_inactive(self, request, queryset):
        queryset.update(status='inactive', is_active=False)
    mark_inactive.short_description = "Mark selected products as Inactive"
    
    def mark_out_of_stock(self, request, queryset):
        queryset.update(status='out_of_stock')
    mark_out_of_stock.short_description = "Mark selected products as Out of Stock"


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'product', 'movement_type_display', 'quantity_display', 
        'reference', 'performed_by', 'created_at'
    ]
    list_filter = ['tenant', 'movement_type', 'created_at']
    search_fields = ['product__name', 'product__sku', 'reference', 'notes']
    readonly_fields = ['id', 'created_at', 'previous_quantity', 'new_quantity', 'total_price']
    
    fieldsets = (
        ('Movement Details', {
            'fields': ('tenant', 'product', 'movement_type', 'quantity', 'unit_price')
        }),
        ('Stock Changes', {
            'fields': ('previous_quantity', 'new_quantity', 'total_price'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('reference', 'notes')
        }),
        ('Metadata', {
            'fields': ('id', 'created_by', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def movement_type_display(self, obj):
        colors = {
            'purchase': 'success',
            'sale': 'danger',
            'return': 'warning',
            'adjustment': 'info',
            'transfer': 'primary',
            'waste': 'secondary',
        }
        color = colors.get(obj.movement_type, 'secondary')
        movement_type = obj.get_movement_type_display()
        return f'<span class="badge bg-{color}">{movement_type}</span>'
    movement_type_display.short_description = 'Type'
    movement_type_display.allow_tags = True
    
    def quantity_display(self, obj):
        if obj.movement_type in ['purchase', 'return']:
            color = '#28a745'
            sign = '+'
        else:
            color = '#dc3545'
            sign = '-'
        quantity = float(obj.quantity) if obj.quantity else 0
        return f'<span style="color: {color}; font-weight: bold;">{sign}{quantity}</span>'
    quantity_display.short_description = 'Quantity'
    quantity_display.allow_tags = True
    
    def performed_by(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else 'System'
    performed_by.short_description = 'Performed By'
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'created_by', 'tenant')


@admin.register(InventoryAlert)
class InventoryAlertAdmin(admin.ModelAdmin):
    list_display = [
        'alert_type_display', 'product', 'severity_display', 
        'message_short', 'status_display', 'created_at'
    ]
    list_filter = ['tenant', 'alert_type', 'is_read', 'is_resolved', 'created_at']
    search_fields = ['product__name', 'message']
    readonly_fields = ['id', 'created_at', 'resolved_at']
    
    fieldsets = (
        ('Alert Details', {
            'fields': ('tenant', 'product', 'alert_type', 'severity', 'message')
        }),
        ('Status', {
            'fields': ('is_read', 'is_resolved', 'resolved_at')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    
    def alert_type_display(self, obj):
        icons = {
            'low_stock': '⚠️',
            'out_of_stock': '❌',
            'expiry': '📅',
            'overstock': '📈',
        }
        icon = icons.get(obj.alert_type, '🔔')
        alert_type = obj.get_alert_type_display()
        return f'{icon} <span class="badge bg-secondary">{alert_type}</span>'
    alert_type_display.short_description = 'Type'
    alert_type_display.allow_tags = True
    
    def severity_display(self, obj):
        severity_colors = {
            'critical': 'danger',
            'warning': 'warning',
            'info': 'info',
        }
        color = severity_colors.get(obj.severity, 'secondary')
        severity = obj.get_severity_display()
        if not severity:
            severity = obj.severity
        return f'<span class="badge bg-{color}">{severity}</span>'
    severity_display.short_description = 'Severity'
    severity_display.allow_tags = True
    
    def message_short(self, obj):
        return obj.message[:50] + '...' if len(obj.message) > 50 else obj.message
    message_short.short_description = 'Message'
    
    def status_display(self, obj):
        if obj.is_resolved:
            return '<span class="badge bg-success">✅ Resolved</span>'
        elif obj.is_read:
            return '<span class="badge bg-info">📖 Read</span>'
        else:
            return '<span class="badge bg-danger">🔴 Unread</span>'
    status_display.short_description = 'Status'
    status_display.allow_tags = True
    
    actions = ['mark_as_read', 'mark_as_unread', 'mark_as_resolved']
    
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)
    mark_as_read.short_description = "Mark selected alerts as Read"
    
    def mark_as_unread(self, request, queryset):
        queryset.update(is_read=False)
    mark_as_unread.short_description = "Mark selected alerts as Unread"
    
    def mark_as_resolved(self, request, queryset):
        from django.utils import timezone
        queryset.update(is_resolved=True, resolved_at=timezone.now())
    mark_as_resolved.short_description = "Mark selected alerts as Resolved"
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product', 'tenant')


admin.site.site_header = 'PharmaPro Administration'
admin.site.site_title = 'PharmaPro Admin'
admin.site.index_title = 'Welcome to PharmaPro Admin Panel'