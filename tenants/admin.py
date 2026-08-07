# apps/tenants/admin.py - COMPLETE WORKING VERSION

from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Count
from django.utils.text import slugify
from .models import Tenant, TenantSettings, SubscriptionLog
from django.contrib import messages

class TenantSettingsInline(admin.StackedInline):
    """Inline admin for TenantSettings"""
    model = TenantSettings
    can_delete = False
    verbose_name_plural = "Settings"
    extra = 0
    fieldsets = (
        ('Notification Settings', {
            'fields': (
                'enable_audit_log', 'enable_notifications',
                'enable_email_notifications', 'enable_sms_notifications'
            )
        }),
        ('Backup Settings', {
            'fields': ('enable_auto_backup', 'backup_frequency')
        }),
        ('Localization', {
            'fields': ('timezone', 'date_format', 'time_format', 
                      'currency', 'language')
        }),
    )


class SubscriptionLogInline(admin.TabularInline):
    """Inline admin for SubscriptionLog"""
    model = SubscriptionLog
    extra = 0
    readonly_fields = ('action', 'details', 'created_at')
    fields = ('action', 'details', 'created_at')
    ordering = ('-created_at',)
    
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """Tenant admin with comprehensive management"""
    
    list_display = (
        'name', 'slug', 'company_name', 'plan', 
        'subscription_status', 'user_count_display', 
        'status_display', 'days_left_display', 'created_at'
    )
    
    list_filter = (
        'plan', 'subscription_status', 'maintenance_mode',
        'allow_registration', 'created_at'
    )
    
    search_fields = (
        'name', 'slug', 'company_name', 'company_email',
        'company_phone', 'domain'
    )
    
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'trial_start_date',
        'stripe_customer_id', 'stripe_subscription_id',
        'storage_used'
    )
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'name', 'slug', 'domain')
        }),
        ('Company Details', {
            'fields': (
                'company_name', 'company_address', 'company_phone',
                'company_email', 'company_website'
            )
        }),
        ('Branding & Customization', {
            'fields': (
                'primary_color', 'secondary_color', 'accent_color',
                'logo', 'favicon'
            )
        }),
        ('Subscription', {
            'fields': (
                'plan', 'subscription_status', 'trial_start_date',
                'trial_end_date', 'subscription_start_date',
                'subscription_end_date', 'stripe_customer_id',
                'stripe_subscription_id'
            )
        }),
        ('Limits & Features', {
            'fields': (
                'max_users', 'max_storage', 'storage_used',
                'max_inventory_items', 'max_suppliers', 'max_sales_records'
            )
        }),
        ('Settings', {
            'fields': (
                'allow_registration', 'require_email_verification',
                'maintenance_mode'
            )
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )
    
    inlines = [TenantSettingsInline, SubscriptionLogInline]
    
    def get_queryset(self, request):
        """Annotate queryset with user count"""
        qs = super().get_queryset(request)
        return qs.annotate(
            user_count=Count('users', distinct=True)
        )
    
    def user_count_display(self, obj):
        """Display user count"""
        count = getattr(obj, 'user_count', 0)
        return count
    user_count_display.short_description = "Users"
    user_count_display.admin_order_field = 'user_count'
    
    def status_display(self, obj):
        """Display active status with simple text"""
        if obj.maintenance_mode:
            return "⚠️ Maintenance"
        if obj.is_active():
            return "✅ Active"
        return "❌ Inactive"
    status_display.short_description = "Status"
    
    def days_left_display(self, obj):
        """Display days left until expiry"""
        days = obj.get_subscription_days_left()
        if days <= 0:
            return "⛔ Expired"
        elif days <= 7:
            return f"⚠️ {days} days"
        return f"✅ {days} days"
    days_left_display.short_description = "Days Left"
    
    def get_readonly_fields(self, request, obj=None):
        """Make some fields readonly for non-superusers"""
        if not request.user.is_superuser:
            return list(self.readonly_fields) + [
                'stripe_customer_id', 'stripe_subscription_id',
                'created_by', 'storage_used'
            ]
        return self.readonly_fields
    
    def save_model(self, request, obj, form, change):
        """Save model and handle suspension"""
        if change:
            # Get old status before saving
            old_obj = Tenant.objects.get(pk=obj.pk)
            old_status = old_obj.subscription_status
            
            # Save the object
            super().save_model(request, obj, form, change)
            
            # If status changed to suspended or expired, logout users
            if old_status != obj.subscription_status and obj.subscription_status in ['suspended', 'expired']:
                from accounts.models import User
                from django.contrib.sessions.models import Session
                
                users = User.objects.filter(tenant=obj, is_active=True)
                for user in users:
                    sessions = Session.objects.filter(
                        session_data__contains=str(user.id)
                    )
                    sessions.delete()
                    user.is_online = False
                    user.save(update_fields=['is_online'])
                
                messages.warning(
                    request,
                    f'Tenant "{obj.name}" is now {obj.subscription_status}. All users have been logged out.'
                )
        else:
            # Creating new tenant
            super().save_model(request, obj, form, change)


@admin.register(TenantSettings)
class TenantSettingsAdmin(admin.ModelAdmin):
    """Tenant settings admin"""
    
    list_display = (
        'tenant', 'enable_notifications', 'enable_email_notifications',
        'enable_auto_backup', 'timezone', 'currency'
    )
    list_filter = (
        'enable_notifications', 'enable_email_notifications',
        'enable_sms_notifications', 'enable_auto_backup',
        'timezone', 'currency'
    )
    search_fields = ('tenant__name', 'tenant__company_name')
    readonly_fields = ('id',)
    
    fieldsets = (
        ('Notification Settings', {
            'fields': (
                'enable_audit_log', 'enable_notifications',
                'enable_email_notifications', 'enable_sms_notifications'
            )
        }),
        ('Backup Settings', {
            'fields': ('enable_auto_backup', 'backup_frequency')
        }),
        ('Localization', {
            'fields': ('timezone', 'date_format', 'time_format', 
                      'currency', 'language')
        }),
    )


@admin.register(SubscriptionLog)
class SubscriptionLogAdmin(admin.ModelAdmin):
    """Subscription log admin"""
    
    list_display = ('tenant', 'action', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('tenant__name', 'tenant__company_name', 'action')
    readonly_fields = ('tenant', 'action', 'details', 'created_at')
    ordering = ('-created_at',)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False