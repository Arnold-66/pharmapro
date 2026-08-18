# apps/inventory/models.py - Complete updated file

from django.db import models
from django.contrib.auth import get_user_model
from tenants.models import Tenant
import uuid
from django.utils import timezone

User = get_user_model()


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories'
    )
    icon = models.CharField(max_length=50, blank=True, null=True)
    color = models.CharField(max_length=7, default='#3498db')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_categories')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'inventory_categories'
        ordering = ['name']
        unique_together = ['tenant', 'name']
    
    def __str__(self):
        return self.name
    
    def get_depth(self):
        depth = 0
        parent = self.parent
        while parent:
            depth += 1
            parent = parent.parent
        return depth

    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.name}"
        return self.name


class Unit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='units')
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_units')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'inventory_units'
        unique_together = ['tenant', 'name']
    
    def __str__(self):
        return f"{self.name} ({self.abbreviation})"


class SaleUnit(models.Model):
    """Model for sale units (Box, Strip, Tablet, etc.) with pricing"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sale_units')
    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='sale_units')
    name = models.CharField(max_length=50)
    abbreviation = models.CharField(max_length=10)
    quantity_per_unit = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'inventory_sale_units'
        unique_together = ['tenant', 'product', 'name']
        ordering = ['product', 'name']
    
    def __str__(self):
        return f"{self.product.name} - {self.name} ({self.quantity_per_unit} base units) @ Ugx{self.selling_price}"


class Product(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('out_of_stock', 'Out of Stock'),
        ('discontinued', 'Discontinued'),
        ('expired', 'Expired'),
        ('decommissioned', 'Decommissioned'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='products')
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)
    barcode = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField()
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, related_name='products')
    
    # Stock information - STORED IN BASE UNIT
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reorder_point = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reorder_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Pricing
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    
    # Expiry and tracking
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    expiry_date = models.DateField(null=True, blank=True)
    manufacturing_date = models.DateField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    shelf_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Images
    image = models.ImageField(upload_to='products/', blank=True, null=True)
    gallery_images = models.JSONField(default=list, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_featured = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    weight = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dimensions = models.CharField(max_length=50, blank=True, null=True)
    
    # NEW: Allow fractional sales
    allow_fractional = models.BooleanField(default=False)
    
    # Additional data
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_products')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'inventory_products'
        ordering = ['name']
        unique_together = ['tenant', 'sku']
    
    def __str__(self):
        return f"{self.name} - {self.sku}"
    
    def is_low_stock(self):
        return self.quantity <= self.reorder_point
    
    def is_out_of_stock(self):
        return self.quantity <= 0
    
    def is_expired(self):
        if self.expiry_date:
            return self.expiry_date < timezone.now().date()
        return False
    
    def days_until_expiry(self):
        if self.expiry_date:
            return (self.expiry_date - timezone.now().date()).days
        return None
    
    def get_sale_units(self):
        return self.sale_units.filter(is_active=True)
    
    def get_default_sale_unit(self):
        return self.sale_units.filter(is_default=True).first()
    
    def get_unit_price(self, unit_name):
        unit = self.sale_units.filter(name__iexact=unit_name).first()
        return unit.selling_price if unit else self.selling_price
    
    def get_unit_quantity(self, unit_name):
        unit = self.sale_units.filter(name__iexact=unit_name).first()
        return unit.quantity_per_unit if unit else 1
    
    def get_unit_by_name(self, unit_name):
        return self.sale_units.filter(name__iexact=unit_name).first()
    
    def check_stock_for_unit(self, unit_name, quantity):
        sale_unit = self.get_unit_by_name(unit_name)
        if sale_unit:
            base_quantity_needed = quantity * sale_unit.quantity_per_unit
            return self.quantity >= base_quantity_needed
        return self.quantity >= quantity


class StockMovement(models.Model):
    MOVEMENT_TYPES = [
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('return', 'Return'),
        ('adjustment', 'Adjustment'),
        ('transfer', 'Transfer'),
        ('waste', 'Waste'),
        ('damaged', 'Damaged Goods'),
        ('stolen', 'Stolen Items'),
        ('lost', 'Lost Items'),
        ('add_stock', 'Add Stock'),
        ('expired', 'Expired Goods'),
        ('decommissioned', 'Decommissioned'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='stock_movements')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    previous_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    new_quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=255, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    sale_unit_name = models.CharField(max_length=50, blank=True, null=True)
    sale_quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # NEW FIELDS
    movement_subtype = models.CharField(max_length=50, blank=True, null=True)
    damage_reason = models.CharField(max_length=200, blank=True, null=True)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_movements')
    approved_at = models.DateTimeField(null=True, blank=True)
    value_loss = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    expiry_action = models.CharField(max_length=50, blank=True, null=True)
    decommission_date = models.DateTimeField(null=True, blank=True)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='stock_movements')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'inventory_stock_movements'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.movement_type} - {self.product.name} - {self.quantity}"
    
    def get_movement_type_display(self):
        return dict(self.MOVEMENT_TYPES).get(self.movement_type, self.movement_type)


class InventoryAlert(models.Model):
    ALERT_TYPES = [
        ('low_stock', 'Low Stock'),
        ('out_of_stock', 'Out of Stock'),
        ('expiry', 'Expiry Soon'),
        ('expired', 'Expired'),
        ('overstock', 'Overstock'),
    ]
    
    SEVERITY_CHOICES = [
        ('critical', 'Critical'),
        ('warning', 'Warning'),
        ('info', 'Info'),
    ]
    
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='inventory_alerts')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    read_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='read_alerts')
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_alerts')
    
    class Meta:
        db_table = 'inventory_alerts'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.alert_type} - {self.product.name}"