# apps/suppliers/models.py
from django.db import models
from django.contrib.auth import get_user_model
from tenants.models import Tenant
from inventory.models import Product, Category
import uuid

User = get_user_model()

class Supplier(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('suspended', 'Suspended'),
        ('blacklisted', 'Blacklisted'),
    ]
    
    SUPPLIER_TYPE = [
        ('manufacturer', 'Manufacturer'),
        ('distributor', 'Distributor'),
        ('wholesaler', 'Wholesaler'),
        ('retailer', 'Retailer'),
        ('importer', 'Importer'),
        ('exporter', 'Exporter'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='suppliers')
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)
    supplier_type = models.CharField(max_length=20, choices=SUPPLIER_TYPE, default='other')
    
    # Contact Information
    contact_person = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=20)
    alternative_phone = models.CharField(max_length=20, blank=True, null=True)
    fax = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    
    # Address
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default='Uganda')
    postal_code = models.CharField(max_length=20, blank=True, null=True)
    
    # Business details
    tax_id = models.CharField(max_length=100, blank=True, null=True)
    registration_number = models.CharField(max_length=100, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_account = models.CharField(max_length=50, blank=True, null=True)
    
    # Payment terms
    payment_terms = models.CharField(max_length=100, default='Net 30')
    payment_method = models.CharField(max_length=100, blank=True, null=True)
    credit_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Total owed
    total_paid = models.DecimalField(max_digits=15, decimal_places=2, default=0)    # Total paid
    total_purchases = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Total purchases
    
    # Categories supplied
    categories = models.ManyToManyField(Category, blank=True, related_name='suppliers')
    
    # Performance metrics
    lead_time_days = models.IntegerField(default=0)
    quality_rating = models.IntegerField(default=0, choices=[(i, i) for i in range(1, 6)])
    reliability_score = models.IntegerField(default=0, choices=[(i, i) for i in range(1, 6)])
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    is_approved = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_suppliers')
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_suppliers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_supplier'
        ordering = ['name']
        unique_together = ['tenant', 'code']
    
    def __str__(self):
        return self.name
    
    def get_available_credit(self):
        """Calculate available credit"""
        return self.credit_limit - self.balance_due
    
    def is_credit_available(self, amount):
        """Check if credit is available for a specific amount"""
        return self.get_available_credit() >= amount
    
    def update_financials(self):
        """Update all financial fields from purchase orders"""
        from django.db.models import Sum
        
        # Get all purchase orders for this supplier
        pos = self.purchase_orders.filter(
            status__in=['ordered', 'received', 'partial', 'approved']
        )
        
        # Calculate total purchases
        total_purchases = pos.aggregate(
            total=Sum('total_amount')
        )['total'] or 0
        
        # Calculate total paid from payments
        total_paid = self.payments.aggregate(
            total=Sum('amount')
        )['total'] or 0
        
        # Calculate balance due
        balance_due = total_purchases - total_paid
        
        # Update fields
        self.total_purchases = total_purchases
        self.total_paid = total_paid
        self.balance_due = balance_due
        self.save(update_fields=['total_purchases', 'total_paid', 'balance_due'])
        
        return {
            'total_purchases': total_purchases,
            'total_paid': total_paid,
            'balance_due': balance_due,
            'available_credit': self.get_available_credit()
        }



class SupplierContact(models.Model):
    """Multiple contacts for a supplier"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_contacts')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='contacts')
    
    name = models.CharField(max_length=255)
    position = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    mobile = models.CharField(max_length=20, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_contacts'
        ordering = ['-is_primary', 'name']
    
    def __str__(self):
        return f"{self.name} - {self.supplier.name}"


class SupplierProduct(models.Model):
    """Products supplied by a supplier with specific pricing"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_products')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='supplier_products')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='supplier_products')
    
    supplier_product_code = models.CharField(max_length=100, blank=True, null=True)
    supplier_product_name = models.CharField(max_length=255, blank=True, null=True)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    min_order_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    lead_time_days = models.IntegerField(default=7)
    is_preferred = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_products'
        unique_together = ['supplier', 'product']
    
    def __str__(self):
        return f"{self.supplier.name} - {self.product.name}"

class SupplierPayment(models.Model):
    """Track payments made to suppliers"""
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('mobile_money', 'Mobile Money'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='supplier_payments')
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='payments')
    
    payment_number = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField()
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='bank_transfer')
    reference_number = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    
    # Purchase order reference (optional)
    purchase_order = models.ForeignKey(
        'PurchaseOrder', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='payments'
    )
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_supplier_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_payments'
        ordering = ['-payment_date', '-created_at']
    
    def __str__(self):
        return f"{self.payment_number} - {self.supplier.name} - Ugx {self.amount}"
    
    def save(self, *args, **kwargs):
        if not self.payment_number:
            # Generate payment number
            import datetime
            year = datetime.datetime.now().year
            count = SupplierPayment.objects.filter(tenant=self.tenant).count() + 1
            self.payment_number = f"SP-{year}{count:06d}"
        super().save(*args, **kwargs)
        # Update supplier financials
        self.supplier.update_financials()


class PurchaseOrder(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('ordered', 'Ordered'),
        ('received', 'Received'),
        ('partial', 'Partially Received'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='purchase_orders')
    po_number = models.CharField(max_length=50, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='purchase_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Dates
    order_date = models.DateTimeField(auto_now_add=True)
    expected_delivery_date = models.DateField()
    actual_delivery_date = models.DateField(null=True, blank=True)
    
    # Financials
    subtotal = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    
    # Approvals
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='approved_pos')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_pos')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_purchase_orders'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.po_number} - {self.supplier.name}"
    
    def save(self, *args, **kwargs):
        if not self.po_number:
            import datetime
            year = datetime.datetime.now().year
            count = PurchaseOrder.objects.filter(tenant=self.tenant).count() + 1
            self.po_number = f"PO-{year}{count:06d}"
        super().save(*args, **kwargs)
        # Update supplier financials
        self.supplier.update_financials()


class PurchaseOrderItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    total_price = models.DecimalField(max_digits=15, decimal_places=2)
    received_quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'suppliers_po_items'
    
    def __str__(self):
        return f"{self.product.name} - {self.quantity}"