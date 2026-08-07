# apps/tenants/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from datetime import timedelta
import uuid
import stripe
from django.conf import settings
from django.utils.text import slugify

User = get_user_model()
stripe.api_key = settings.STRIPE_SECRET_KEY

def default_trial_end_date():
    return timezone.now() + timedelta(days=14)


class Tenant(models.Model):
    SUBSCRIPTION_STATUS = [
        ('active', 'Active'),
        ('trial', 'Trial'),
        ('expired', 'Expired'),
        ('suspended', 'Suspended'),
        ('cancelled', 'Cancelled'),
    ]
    
    PLAN_CHOICES = [
        ('free', 'Free Trial'),
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]
    
    # Plan limits
    PLAN_LIMITS = {
        'free': {'max_users': 5, 'max_products': 100, 'max_sales': 500, 'price': 0},
        'starter': {'max_users': 5, 'max_products': 100, 'max_sales': 500, 'price': 29000},
        'professional': {'max_users': 25, 'max_products': 0, 'max_sales': 0, 'price': 79000},
        'enterprise': {'max_users': 0, 'max_products': 0, 'max_sales': 0, 'price': 199000},
    }
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, max_length=100)
    domain = models.CharField(max_length=255, unique=True, null=True, blank=True)
    
    # Branding and customization
    primary_color = models.CharField(max_length=7, default='#2c3e50')
    secondary_color = models.CharField(max_length=7, default='#3498db')
    accent_color = models.CharField(max_length=7, default='#e74c3c')
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    favicon = models.ImageField(upload_to='tenant_favicons/', blank=True, null=True)
    company_name = models.CharField(max_length=255)
    company_address = models.TextField()
    company_phone = models.CharField(max_length=20)
    company_email = models.EmailField()
    company_website = models.URLField(blank=True, null=True)
    
    # Subscription
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='free')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS, default='trial')
    trial_start_date = models.DateTimeField(auto_now_add=True)
    trial_end_date = models.DateTimeField(
        default=default_trial_end_date
    )
       
    
    subscription_start_date = models.DateTimeField(null=True, blank=True)
    subscription_end_date = models.DateTimeField(null=True, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_price_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Features and limits
    max_users = models.IntegerField(default=5)
    max_storage = models.BigIntegerField(default=1073741824)  # 1GB default
    storage_used = models.BigIntegerField(default=0)
    max_inventory_items = models.IntegerField(default=100)
    max_suppliers = models.IntegerField(default=20)
    max_sales_records = models.IntegerField(default=500)
    
    # Settings
    allow_registration = models.BooleanField(default=True)
    require_email_verification = models.BooleanField(default=True)
    maintenance_mode = models.BooleanField(default=False)
    
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_tenants')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenants_tenant'
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        """Auto-generate slug from company name if not provided"""
        if not self.slug:
            # Generate slug from company_name
            self.slug = slugify(self.company_name or self.name)
            
            # Ensure uniqueness
            original_slug = self.slug
            counter = 1
            while Tenant.objects.filter(slug=self.slug).exclude(id=self.id).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1
        
        if not self.trial_end_date:
            self.trial_end_date = timezone.now() + timedelta(days=14)
        
        # Set plan limits
        if self.plan in self.PLAN_LIMITS:
            limits = self.PLAN_LIMITS[self.plan]
            if limits['max_users'] > 0:
                self.max_users = limits['max_users']
            if limits['max_products'] > 0:
                self.max_inventory_items = limits['max_products']
            if limits['max_sales'] > 0:
                self.max_sales_records = limits['max_sales']
        
        super().save(*args, **kwargs)
    
    def is_trial_active(self):
        return timezone.now() <= self.trial_end_date
    
    def is_subscription_active(self):
        if self.subscription_end_date:
            return timezone.now() <= self.subscription_end_date
        return False
    
    def days_until_expiry(self):
        if self.subscription_end_date:
            delta = self.subscription_end_date - timezone.now()
            return delta.days
        return 0
    
    def is_active(self):
        return self.subscription_status in ['active', 'trial'] and not self.maintenance_mode
    
    def get_subscription_days_left(self):
        if self.subscription_end_date:
            delta = self.subscription_end_date - timezone.now()
            return delta.days
        elif self.trial_end_date:
            delta = self.trial_end_date - timezone.now()
            return delta.days
        return 0
    
    def is_expired(self):
        """Check if tenant subscription is expired"""
        if self.subscription_status == 'expired':
            return True
        
        if self.subscription_status == 'trial':
            if self.trial_end_date:
                return timezone.now() > self.trial_end_date
            return False
        
        if self.subscription_status == 'active':
            if self.subscription_end_date:
                return timezone.now() > self.subscription_end_date
            return False
        
        # For other statuses, check both dates
        if self.subscription_end_date and timezone.now() > self.subscription_end_date:
            return True
        
        if self.trial_end_date and timezone.now() > self.trial_end_date:
            return True
        
        return False
    

    def get_days_until_expiry(self):
        """Get days until subscription expires"""
        now = timezone.now()
        
        # For trial tenants, use trial_end_date
        if self.subscription_status == 'trial':
            if self.trial_end_date:
                delta = self.trial_end_date - now
                # If trial_end_date is in the past, return 0
                if delta.total_seconds() <= 0:
                    return 0
                return delta.days
            return 0
        
        # For active tenants, use subscription_end_date
        if self.subscription_status == 'active':
            if self.subscription_end_date:
                delta = self.subscription_end_date - now
                if delta.total_seconds() <= 0:
                    return 0
                return delta.days
            return 0
        
        # For other statuses, check if there's any end date
        if self.subscription_end_date:
            delta = self.subscription_end_date - now
            if delta.total_seconds() <= 0:
                return 0
            return delta.days
        
        # Check trial_end_date as fallback for other statuses
        if self.trial_end_date:
            delta = self.trial_end_date - now
            if delta.total_seconds() <= 0:
                return 0
            return delta.days
        
        return 0
    
    def get_expiry_warning_days(self):
        """Get days until expiry warning (3 days warning)"""
        days = self.get_days_until_expiry()
        if days <= 3 and days > 0:
            return days
        return None
    
    def get_status_display(self):
        """Get a user-friendly status display"""
        if self.subscription_status == 'suspended':
            return 'Suspended'
        elif self.subscription_status == 'expired':
            return 'Expired'
        elif self.subscription_status == 'active':
            return 'Active'
        elif self.subscription_status == 'trial':
            return 'Trial'
        elif self.subscription_status == 'cancelled':
            return 'Cancelled'
        return 'Unknown'
    
    def get_plan_price(self):
        """Get the price for the current plan in UGX"""
        return self.PLAN_LIMITS.get(self.plan, {}).get('price', 0)
    
    def get_plan_limit(self, key):
        """Get a specific plan limit"""
        return self.PLAN_LIMITS.get(self.plan, {}).get(key, 0)
    
    def create_stripe_customer(self):
        if not self.stripe_customer_id:
            customer = stripe.Customer.create(
                email=self.company_email,
                name=self.company_name,
                metadata={'tenant_id': str(self.id)}
            )
            self.stripe_customer_id = customer.id
            self.save()
        return self.stripe_customer_id



class TenantSettings(models.Model):
    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='settings')
    
    # Basic settings
    timezone = models.CharField(max_length=50, default='UTC')
    date_format = models.CharField(max_length=20, default='YYYY-MM-DD')
    time_format = models.CharField(max_length=20, default='HH:mm')
    currency = models.CharField(max_length=10, default='UGX')
    language = models.CharField(max_length=10, default='en')
    
    # Notification settings
    enable_audit_log = models.BooleanField(default=True)
    enable_notifications = models.BooleanField(default=True)
    enable_email_notifications = models.BooleanField(default=True)
    enable_sms_notifications = models.BooleanField(default=False)
    enable_auto_backup = models.BooleanField(default=False)
    backup_frequency = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ], default='weekly')
    
    # ===== TAX SETTINGS - ADD THESE =====
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.00)
    tax_inclusive = models.BooleanField(default=False)
    
    # ===== INVOICE SETTINGS - ADD THESE =====
    invoice_prefix = models.CharField(max_length=20, default='INV')
    invoice_footer = models.TextField(blank=True, null=True)
    
    # Payment settings
    payment_terms = models.CharField(max_length=50, default='Due on receipt')
    late_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'tenants_settings'
    
    def __str__(self):
        return f"Settings for {self.tenant.name}"


class SubscriptionLog(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='subscription_logs')
    action = models.CharField(max_length=50)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'tenants_subscription_logs'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.tenant.name} - {self.action} at {self.created_at}"


@receiver(post_save, sender=Tenant)
def create_tenant_settings(sender, instance, created, **kwargs):
    if created:
        TenantSettings.objects.create(tenant=instance)