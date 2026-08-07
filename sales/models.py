# apps/sales/models.py - Update the Sale model

from django.db import models
from django.contrib.auth import get_user_model
from tenants.models import Tenant
from django.conf import settings
import uuid

User = get_user_model()


class Sale(models.Model):
    PAYMENT_STATUS = [
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('unpaid', 'Unpaid'),
        ('refunded', 'Refunded'),
    ]
    
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('credit_card', 'Credit Card'),
        ('debit_card', 'Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('mobile_money', 'Mobile Money'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='sales')
    invoice_number = models.CharField(max_length=50, unique=True)
    
    # Get default tax rate from tenant settings or use 18%
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)

    # Customer info - simplified
    customer_name = models.CharField(max_length=255, blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Dates
    sale_date = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField()
    
    # Financials
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    change_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)  # Change returned to customer
    
    # Payment
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='unpaid')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='cash')
    payment_date = models.DateTimeField(null=True, blank=True)
    
    # Delivery
    shipping_address = models.TextField(blank=True, null=True)
    delivery_status = models.CharField(max_length=20, choices=[
        ('pending', 'Pending'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ], default='pending')
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    internal_notes = models.TextField(blank=True, null=True)
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_sales')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'sales_sales'
        ordering = ['-sale_date']
    
    def __str__(self):
        return f"{self.invoice_number} - {self.customer_name or 'Walk-in Customer'}"
    
    def calculate_balance(self):
        """Calculate balance due and change amount"""
        self.balance_due = self.total_amount - self.paid_amount
        self.change_amount = max(0, self.paid_amount - self.total_amount)
        return self.balance_due
    
    def update_payment_status(self):
        """Update payment status based on balance"""
        if self.balance_due < 0:
            # Overpaid - set to paid status but keep change_amount
            self.payment_status = 'paid'
        elif self.balance_due == 0:
            self.payment_status = 'paid'
        elif self.paid_amount > 0:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'unpaid'
        
        # Always recalculate change
        self.change_amount = max(0, self.paid_amount - self.total_amount)
        self.save()
    
    @classmethod
    def get_default_tax_rate(cls, tenant):
        """Get default tax rate from tenant settings or use 18%"""
        try:
            from tenants.models import TenantSettings
            settings_obj = TenantSettings.objects.get(tenant=tenant)
            # If tax_rate is 0 or None, return 18 as default
            tax_rate = settings_obj.tax_rate
            if tax_rate is None or float(tax_rate) == 0:
                return 18.00
            return float(tax_rate)
        except TenantSettings.DoesNotExist:
            return 18.00
        except Exception:
            return 18.00


class SaleItem(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey('inventory.Product', on_delete=models.CASCADE)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sales_items'
    
    def __str__(self):
        return f"{self.product.name} - {self.quantity}"


class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('credit_card', 'Credit Card'),
        ('debit_card', 'Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('cheque', 'Cheque'),
        ('mobile_money', 'Mobile Money'),
        ('other', 'Other'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='payments')
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payer_name = models.CharField(max_length=255, blank=True, null=True)
    reference = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'sales_payments'
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update sale payment status with full payment amounts
        self.sale.paid_amount = self.sale.payments.aggregate(total=models.Sum('amount'))['total'] or 0
        self.sale.balance_due = self.sale.total_amount - self.sale.paid_amount
        self.sale.change_amount = max(0, self.sale.paid_amount - self.sale.total_amount)
        self.sale.update_payment_status()
    
    def __str__(self):
        return f"Payment of {self.amount} for {self.sale.invoice_number}"