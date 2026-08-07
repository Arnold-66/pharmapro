# apps/accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.conf import settings
import uuid

class User(AbstractUser):
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('admin', 'Organization Admin'),
        ('manager', 'Manager'),
        ('staff', 'Staff'),
        ('viewer', 'Viewer'),
        ('supervisor', 'Supervisor')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    phone = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        validators=[FileExtensionValidator(['jpg', 'jpeg', 'png', 'gif'])],
        blank=True,
        null=True
    )
    bio = models.TextField(blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.UUIDField(default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    is_online = models.BooleanField(default=False)
    last_activity = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # ADD THIS FIELD - ForeignKey to Tenant
    tenant = models.ForeignKey(
        'tenants.Tenant',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users'
    )
    
    # Custom permissions
    can_create = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_view = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'accounts_user'
        permissions = [
            ("can_manage_tenant", "Can manage tenant settings"),
            ("can_manage_users", "Can manage users"),
            ("can_view_reports", "Can view reports"),
            ("can_export_data", "Can export data"),
        ]
    
    def __str__(self):
        return f"{self.get_full_name() or self.username}"
    
    def get_permissions_list(self):
        """Get all permissions for the user"""
        permissions = []
        if self.is_superuser:
            return ['*']  # All permissions
            
        # Check object-level permissions
        if self.can_create:
            permissions.append('create')
        if self.can_edit:
            permissions.append('edit')
        if self.can_delete:
            permissions.append('delete')
        if self.can_view:
            permissions.append('view')
            
        # Check group permissions
        for group in self.groups.all():
            for permission in group.permissions.all():
                permissions.append(permission.codename)
                
        return list(set(permissions))
    
    def has_permission(self, permission):
        """Check if user has a specific permission"""
        if self.is_superuser:
            return True
        return permission in self.get_permissions_list()
    



    def send_verification_email(self, request):
        """Send email verification link"""
        from django.core.mail import send_mail
        from django.template.loader import render_to_string
        from django.utils.html import strip_tags
        from django.conf import settings
        import uuid
        
        subject = 'Verify Your Email Address - PharmaPro'
        
        # Ensure we have a token
        if not self.email_verification_token:
            self.email_verification_token = uuid.uuid4()
            self.save()
        
        # Generate verification URL - FIX: Add 'accounts/' prefix
        verification_url = request.build_absolute_uri(
            f'/accounts/verify-email/?token={self.email_verification_token}'
        )
        
        context = {
            'user': self,
            'verification_url': verification_url,
            'site_name': 'PharmaPro',
            'support_email': settings.DEFAULT_FROM_EMAIL,
        }
        
        try:
            html_message = render_to_string('accounts/email/verification.html', context)
            plain_message = strip_tags(html_message)
        except Exception:
            # Fallback if template doesn't exist
            html_message = f"""
            <h1>Welcome to PharmaPro!</h1>
            <p>Hello {self.get_full_name() or self.username},</p>
            <p>Please verify your email address by clicking the link below:</p>
            <p><a href="{verification_url}">{verification_url}</a></p>
            <p>If you did not create an account, please ignore this email.</p>
            <p>Best regards,<br>The PharmaPro Team</p>
            """
            plain_message = f"""
            Welcome to PharmaPro!
            
            Hello {self.get_full_name() or self.username},
            
            Please verify your email address by clicking the link below:
            {verification_url}
            
            If you did not create an account, please ignore this email.
            
            Best regards,
            The PharmaPro Team
            """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [self.email],
            html_message=html_message,
            fail_silently=False,
        )


    def save(self, *args, **kwargs):
        # Set username to email if not provided (for new users)
        if not self.username and self.email:
            self.username = self.email
        
        # Generate verification token if not set
        if not self.email_verification_token:
            self.email_verification_token = uuid.uuid4()
        
        super().save(*args, **kwargs)

class UserActivity(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    action = models.CharField(max_length=255)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    
    class Meta:
        db_table = 'accounts_user_activity'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.user.username} - {self.action} at {self.timestamp}"
    

# apps/accounts/models.py - Add this model

class Notification(models.Model):
    NOTIFICATION_TYPES = [
        ('info', 'Information'),
        ('success', 'Success'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('alert', 'Alert'),
    ]
    
    NOTIFICATION_CATEGORIES = [
        ('system', 'System'),
        ('user', 'User Management'),
        ('inventory', 'Inventory'),
        ('sales', 'Sales'),
        ('subscription', 'Subscription'),
        ('security', 'Security'),
        ('general', 'General'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey('tenants.Tenant', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES, default='info')
    category = models.CharField(max_length=20, choices=NOTIFICATION_CATEGORIES, default='general')
    is_read = models.BooleanField(default=False)
    is_global = models.BooleanField(default=False)  # If True, shown to all users in tenant
    link = models.CharField(max_length=500, blank=True, null=True)
    link_text = models.CharField(max_length=100, blank=True, null=True)
    icon = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'accounts_notification'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tenant', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['is_read']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.user or self.tenant}"
    
    def mark_as_read(self):
        self.is_read = True
        self.read_at = timezone.now()
        self.save()
    
    def mark_as_unread(self):
        self.is_read = False
        self.read_at = None
        self.save()
    
    @classmethod
    def create_notification(cls, tenant, user, title, message, notification_type='info', 
                           category='general', link=None, link_text=None, icon=None, 
                           is_global=False, expires_at=None, metadata=None):
        """Helper method to create a notification"""
        notification = cls(
            tenant=tenant,
            user=user if not is_global else None,
            title=title,
            message=message,
            notification_type=notification_type,
            category=category,
            link=link,
            link_text=link_text,
            icon=icon,
            is_global=is_global,
            expires_at=expires_at,
            metadata=metadata or {}
        )
        notification.save()
        return notification
    
    @classmethod
    def create_global_notification(cls, tenant, title, message, notification_type='info',
                                   category='general', link=None, link_text=None, icon=None,
                                   expires_at=None, metadata=None):
        """Create a notification for all users in a tenant"""
        return cls.create_notification(
            tenant=tenant,
            user=None,
            title=title,
            message=message,
            notification_type=notification_type,
            category=category,
            link=link,
            link_text=link_text,
            icon=icon,
            is_global=True,
            expires_at=expires_at,
            metadata=metadata
        )
    
    @classmethod
    def get_unread_count(cls, user):
        """Get unread notification count for a user"""
        return cls.objects.filter(
            models.Q(user=user) | models.Q(tenant=user.tenant, is_global=True),
            is_read=False,
            expires_at__isnull=True
        ).count()
    
    @classmethod
    def get_user_notifications(cls, user, limit=20):
        """Get notifications for a user"""
        return cls.objects.filter(
            models.Q(user=user) | models.Q(tenant=user.tenant, is_global=True),
            expires_at__isnull=True
        ).exclude(
            expires_at__lte=timezone.now()
        ).order_by('-created_at')[:limit]
    


# apps/accounts/models.py - Add SystemSettings model

class SystemSettings(models.Model):
    """Global system settings for superadmin"""
    
    # General Settings
    site_name = models.CharField(max_length=100, default='PharmaPro')
    site_url = models.URLField(default='https://pharmapro.com')
    admin_email = models.EmailField(blank=True, null=True)
    support_email = models.EmailField(default='support@pharmapro.com')
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.TextField(default='We are currently performing maintenance. Please check back later.')
    
    # Branding
    primary_color = models.CharField(max_length=7, default='#2c3e50')
    secondary_color = models.CharField(max_length=7, default='#3498db')
    accent_color = models.CharField(max_length=7, default='#e74c3c')
    site_logo = models.ImageField(upload_to='system/logos/', blank=True, null=True)
    site_favicon = models.ImageField(upload_to='system/favicons/', blank=True, null=True)
    
    # Security
    allow_registration = models.BooleanField(default=True)
    require_verification = models.BooleanField(default=True)
    session_timeout = models.IntegerField(default=60)  # minutes
    force_ssl = models.BooleanField(default=False)
    
    # Email Settings
    smtp_host = models.CharField(max_length=255, default='smtp.gmail.com')
    smtp_port = models.IntegerField(default=587)
    smtp_username = models.CharField(max_length=255, blank=True, null=True)
    smtp_password = models.CharField(max_length=255, blank=True, null=True)
    use_tls = models.BooleanField(default=True)
    
    # Stripe Settings
    stripe_publishable_key = models.CharField(max_length=255, blank=True, null=True)
    stripe_secret_key = models.CharField(max_length=255, blank=True, null=True)
    stripe_webhook_secret = models.CharField(max_length=255, blank=True, null=True)
    stripe_test_mode = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'accounts_system_settings'
        verbose_name = 'System Setting'
        verbose_name_plural = 'System Settings'
    
    def __str__(self):
        return f"System Settings (v{self.id})"