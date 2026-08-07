# apps/accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, UserActivity
from tenants.models import Tenant

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    """Custom User admin with tenant support"""
    
    list_display = (
        'username', 'email', 'first_name', 'last_name', 
        'role', 'tenant', 'is_active', 'is_online', 'email_verified'
    )
    list_filter = (
        'is_active', 'is_staff', 'is_superuser', 'role', 
        'tenant', 'email_verified', 'is_online'
    )
    search_fields = (
        'username', 'email', 'first_name', 'last_name', 
        'phone', 'bio'
    )
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (_('Personal info'), {
            'fields': (
                'first_name', 'last_name', 'email', 'phone', 
                'bio', 'profile_picture'
            )
        }),
        (_('Permissions'), {
            'fields': (
                'is_active', 'is_staff', 'is_superuser', 
                'groups', 'user_permissions', 'role',
                'can_create', 'can_edit', 'can_delete', 'can_view'
            ),
        }),
        (_('Tenant & Organization'), {
            'fields': ('tenant',),
        }),
        (_('Important dates'), {
            'fields': (
                'last_login', 'date_joined', 'last_activity',
                'created_at', 'updated_at'
            )
        }),
        (_('Email Verification'), {
            'fields': ('email_verified', 'email_verification_token'),
        }),
        (_('Status'), {
            'fields': ('is_online',),
        }),
    )
    
    readonly_fields = (
        'created_at', 'updated_at', 'email_verification_token',
        'last_activity', 'date_joined', 'last_login'
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username', 'email', 'password1', 'password2',
                'first_name', 'last_name', 'role', 'tenant'
            ),
        }),
    )
    
    def get_queryset(self, request):
        """Filter queryset based on user permissions"""
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Non-superusers can only see users in their tenant
        if request.user.tenant:
            return qs.filter(tenant=request.user.tenant)
        return qs.none()
    
    def save_model(self, request, obj, form, change):
        """Set tenant when creating user"""
        if not change and not obj.tenant:
            obj.tenant = request.user.tenant
        super().save_model(request, obj, form, change)
    
    def get_form(self, request, obj=None, **kwargs):
        """Customize form based on user permissions"""
        form = super().get_form(request, obj, **kwargs)
        if not request.user.is_superuser:
            # Non-superusers can't change superuser status or tenant
            if 'is_superuser' in form.base_fields:
                form.base_fields['is_superuser'].disabled = True
            if 'tenant' in form.base_fields:
                form.base_fields['tenant'].queryset = Tenant.objects.filter(
                    id=request.user.tenant.id
                )
        return form


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    """User activity admin"""
    
    list_display = ('user', 'action', 'model_name', 'timestamp', 'ip_address')
    list_filter = ('action', 'model_name', 'timestamp')
    search_fields = ('user__username', 'user__email', 'action', 'object_id')
    readonly_fields = ('user', 'action', 'model_name', 'object_id', 
                      'timestamp', 'ip_address', 'user_agent')
    ordering = ('-timestamp',)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False