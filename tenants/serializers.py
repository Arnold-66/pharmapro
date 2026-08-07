# apps/tenants/serializers.py
from rest_framework import serializers
from django.utils import timezone
from django.core.validators import validate_slug
from django.core.exceptions import ValidationError
from .models import Tenant, TenantSettings, SubscriptionLog
from accounts.models import User
from accounts.serializers import UserSerializer
import stripe
from django.conf import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

class TenantSettingsSerializer(serializers.ModelSerializer):
    """Tenant settings serializer"""
    class Meta:
        model = TenantSettings
        fields = [
            'id', 'enable_audit_log', 'enable_notifications',
            'enable_email_notifications', 'enable_sms_notifications',
            'enable_auto_backup', 'backup_frequency', 'timezone',
            'date_format', 'time_format', 'currency', 'language'
        ]
        read_only_fields = ['id']


class TenantSerializer(serializers.ModelSerializer):
    """Tenant model serializer"""
    settings = TenantSettingsSerializer(read_only=True)
    created_by_name = serializers.SerializerMethodField()
    days_until_expiry = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    usage_stats = serializers.SerializerMethodField()
    
    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'slug', 'domain', 'primary_color',
            'secondary_color', 'accent_color', 'logo', 'favicon',
            'company_name', 'company_address', 'company_phone',
            'company_email', 'company_website', 'plan',
            'subscription_status', 'trial_start_date', 'trial_end_date',
            'subscription_start_date', 'subscription_end_date',
            'stripe_customer_id', 'stripe_subscription_id',
            'max_users', 'max_storage', 'storage_used',
            'max_inventory_items', 'max_suppliers', 'max_sales_records',
            'allow_registration', 'require_email_verification',
            'maintenance_mode', 'created_by', 'created_by_name',
            'settings', 'days_until_expiry', 'is_active', 'usage_stats',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'created_by', 'stripe_customer_id',
            'stripe_subscription_id', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            'slug': {'validators': [validate_slug]}
        }
    
    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None
    
    def get_days_until_expiry(self, obj):
        return obj.get_subscription_days_left()
    
    def get_is_active(self, obj):
        return obj.is_active()
    
    def get_usage_stats(self, obj):
        """Get usage statistics for the tenant"""
        return {
            'total_users': User.objects.filter(tenant=obj).count(),
            'total_products': obj.products.count(),
            'total_suppliers': obj.suppliers.count(),
            'total_sales': obj.sales.count(),
            'storage_used_percentage': int((obj.storage_used / obj.max_storage) * 100) if obj.max_storage > 0 else 0,
        }
    
    def validate_slug(self, value):
        """Validate slug is unique"""
        if Tenant.objects.filter(slug=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("This slug is already taken.")
        return value
    
    def create(self, validated_data):
        """Create tenant with default settings"""
        created_by = self.context.get('request').user if self.context.get('request') else None
        
        tenant = Tenant.objects.create(
            created_by=created_by,
            **validated_data
        )
        
        # Create tenant settings
        TenantSettings.objects.create(tenant=tenant)
        
        return tenant
    
    def update(self, instance, validated_data):
        """Update tenant with validation"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # If subscription status changes to suspended, handle it
        if 'subscription_status' in validated_data:
            if validated_data['subscription_status'] == 'suspended':
                SubscriptionLog.objects.create(
                    tenant=instance,
                    action='suspended',
                    details={'reason': 'Manual suspension'}
                )
        
        instance.save()
        return instance


class TenantCreateSerializer(serializers.Serializer):
    """Serializer for tenant registration"""
    # Tenant details
    company_name = serializers.CharField(max_length=255, required=True)
    slug = serializers.CharField(max_length=100, required=True, validators=[validate_slug])
    company_address = serializers.CharField(required=True)
    company_phone = serializers.CharField(max_length=20, required=True)
    company_email = serializers.EmailField(required=True)
    plan = serializers.ChoiceField(choices=Tenant.PLAN_CHOICES, default='starter')
    
    # Admin user details
    admin_email = serializers.EmailField(required=True)
    admin_first_name = serializers.CharField(max_length=150, required=True)
    admin_last_name = serializers.CharField(max_length=150, required=True)
    admin_password = serializers.CharField(write_only=True, min_length=8, required=True)
    
    # Payment details
    payment_method_id = serializers.CharField(required=True)
    
    def validate_slug(self, value):
        """Validate slug is unique"""
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("This slug is already taken.")
        return value
    
    def validate_admin_email(self, value):
        """Validate admin email is unique"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def validate_company_email(self, value):
        """Validate company email"""
        if Tenant.objects.filter(company_email=value).exists():
            raise serializers.ValidationError("A tenant with this email already exists.")
        return value
    
    def create(self, validated_data):
        """Create tenant and admin user"""
        from django.db import transaction
        
        with transaction.atomic():
            # Create admin user
            admin_user = User.objects.create_user(
                username=validated_data['admin_email'],
                email=validated_data['admin_email'],
                password=validated_data['admin_password'],
                first_name=validated_data['admin_first_name'],
                last_name=validated_data['admin_last_name'],
                role='admin',
                is_active=False,  # Will be activated after email verification
                can_create=True,
                can_edit=True,
                can_delete=True,
                can_view=True
            )
            
            # Create tenant
            tenant = Tenant.objects.create(
                name=validated_data['company_name'],
                slug=validated_data['slug'],
                company_name=validated_data['company_name'],
                company_address=validated_data['company_address'],
                company_phone=validated_data['company_phone'],
                company_email=validated_data['company_email'],
                plan=validated_data['plan'],
                subscription_status='trial',
                created_by=admin_user,
                max_users=5 if validated_data['plan'] == 'starter' else 25 if validated_data['plan'] == 'professional' else 100
            )
            
            # Update user with tenant
            admin_user.tenant = tenant
            admin_user.save()
            
            # Create tenant settings
            TenantSettings.objects.create(tenant=tenant)
            
            # Create Stripe customer
            try:
                customer = stripe.Customer.create(
                    email=validated_data['company_email'],
                    name=validated_data['company_name'],
                    metadata={'tenant_id': str(tenant.id)}
                )
                tenant.stripe_customer_id = customer.id
                
                # Attach payment method
                payment_method = stripe.PaymentMethod.attach(
                    validated_data['payment_method_id'],
                    customer=customer.id
                )
                
                # Set as default payment method
                stripe.Customer.modify(
                    customer.id,
                    invoice_settings={'default_payment_method': validated_data['payment_method_id']}
                )
                
                tenant.save()
                
            except stripe.error.StripeError as e:
                # If Stripe fails, still create tenant but mark payment as pending
                SubscriptionLog.objects.create(
                    tenant=tenant,
                    action='payment_failed',
                    details={'error': str(e)}
                )
            
            # Log subscription start
            SubscriptionLog.objects.create(
                tenant=tenant,
                action='trial_started',
                details={'plan': validated_data['plan']}
            )
            
            return {
                'tenant': tenant,
                'user': admin_user
            }


class TenantUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating tenant"""
    class Meta:
        model = Tenant
        fields = [
            'name', 'primary_color', 'secondary_color', 'accent_color',
            'logo', 'favicon', 'company_name', 'company_address',
            'company_phone', 'company_email', 'company_website',
            'allow_registration', 'require_email_verification'
        ]


class SubscriptionLogSerializer(serializers.ModelSerializer):
    """Subscription log serializer"""
    tenant_name = serializers.SerializerMethodField()
    
    class Meta:
        model = SubscriptionLog
        fields = [
            'id', 'tenant', 'tenant_name', 'action',
            'details', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_tenant_name(self, obj):
        return obj.tenant.name if obj.tenant else None


class SubscriptionSerializer(serializers.Serializer):
    """Subscription management serializer"""
    plan = serializers.ChoiceField(choices=Tenant.PLAN_CHOICES, required=True)
    payment_method_id = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        """Validate subscription data"""
        tenant = self.context.get('tenant')
        if not tenant:
            raise serializers.ValidationError("No tenant found.")
        
        # Check if tenant has Stripe customer ID
        if not tenant.stripe_customer_id:
            raise serializers.ValidationError("No Stripe customer found. Please contact support.")
        
        return data


class SubscriptionRenewSerializer(serializers.Serializer):
    """Subscription renewal serializer"""
    payment_method_id = serializers.CharField(required=True)
    
    def validate(self, data):
        """Validate renewal data"""
        tenant = self.context.get('tenant')
        if not tenant:
            raise serializers.ValidationError("No tenant found.")
        
        if not tenant.stripe_customer_id:
            raise serializers.ValidationError("No Stripe customer found. Please contact support.")
        
        return data


class StripeWebhookSerializer(serializers.Serializer):
    """Stripe webhook serializer"""
    id = serializers.CharField(required=True)
    object = serializers.CharField(required=True)
    type = serializers.CharField(required=True)
    data = serializers.JSONField(required=True)