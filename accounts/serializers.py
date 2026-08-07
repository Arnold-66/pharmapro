# apps/accounts/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from .models import User, UserActivity
from tenants.models import Tenant
import re

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    """User model serializer"""
    full_name = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    profile_picture_url = serializers.SerializerMethodField()
    tenant_name = serializers.SerializerMethodField()
    online_status = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'role', 'profile_picture', 'profile_picture_url',
            'bio', 'email_verified', 'is_active', 'is_online', 'online_status',
            'can_create', 'can_edit', 'can_delete', 'can_view',
            'permissions', 'tenant', 'tenant_name',
            'last_activity', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'email_verified', 'last_activity', 'created_at', 'updated_at']
        extra_kwargs = {
            'password': {'write_only': True},
            'username': {'validators': [EmailValidator()]}
        }
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    
    def get_permissions(self, obj):
        return obj.get_permissions_list()
    
    def get_profile_picture_url(self, obj):
        if obj.profile_picture and hasattr(obj.profile_picture, 'url'):
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None
    
    def get_tenant_name(self, obj):
        if hasattr(obj, 'tenant') and obj.tenant:
            return obj.tenant.name
        return None
    
    def get_online_status(self, obj):
        """Get online status with last activity time"""
        if obj.is_online:
            # Check if user has been inactive for more than 15 minutes
            if obj.last_activity and (timezone.now() - obj.last_activity).seconds > 900:
                return 'idle'
            return 'online'
        return 'offline'
    
    def validate_email(self, value):
        """Validate email is unique"""
        if User.objects.filter(email=value).exclude(id=self.instance.id if self.instance else None).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value
    
    def create(self, validated_data):
        """Create user with password hashing"""
        password = validated_data.pop('password', None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        user.save()
        return user
    
    def update(self, instance, validated_data):
        """Update user with password hashing if needed"""
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UserCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new users"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)
    
    class Meta:
        model = User
        fields = [
            'email', 'username', 'password', 'password_confirm',
            'first_name', 'last_name', 'phone', 'role',
            'can_create', 'can_edit', 'can_delete', 'can_view'
        ]
    
    def validate(self, data):
        """Validate passwords match"""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return data
    
    def create(self, validated_data):
        """Create user with proper password hashing"""
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class UserLoginSerializer(serializers.Serializer):
    """User login serializer"""
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    tenant_slug = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, data):
        """Validate user credentials"""
        username = data.get('username')
        password = data.get('password')
        tenant_slug = data.get('tenant_slug', '')
        
        # Check if user exists
        try:
            user = User.objects.get(username=username) | User.objects.get(email=username)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid username or password.")
        
        # Check if user is active
        if not user.is_active:
            raise serializers.ValidationError("Your account has been deactivated. Please contact support.")
        
        # Check if email is verified
        if not user.email_verified:
            raise serializers.ValidationError("Please verify your email address before logging in.")
        
        # Check tenant if provided
        if tenant_slug:
            try:
                tenant = Tenant.objects.get(slug=tenant_slug)
                if user.tenant_id != tenant.id:
                    raise serializers.ValidationError("You don't have access to this organization.")
            except Tenant.DoesNotExist:
                raise serializers.ValidationError("Organization not found.")
        
        # Authenticate
        user = authenticate(username=username, password=password)
        if not user:
            raise serializers.ValidationError("Invalid username or password.")
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Log activity
        UserActivity.objects.create(
            user=user,
            action='User logged in',
            model_name='User',
            object_id=str(user.id),
            ip_address=self.context.get('request', {}).META.get('REMOTE_ADDR'),
            user_agent=self.context.get('request', {}).META.get('HTTP_USER_AGENT')
        )
        
        # Update last activity
        user.last_activity = timezone.now()
        user.is_online = True
        user.save(update_fields=['last_activity', 'is_online'])
        
        data = {
            'user': UserSerializer(user, context=self.context).data,
            'access_token': str(refresh.access_token),
            'refresh_token': str(refresh),
            'tenant': {
                'id': user.tenant.id,
                'name': user.tenant.name,
                'slug': user.tenant.slug,
            } if user.tenant else None
        }
        return data


class UserActivitySerializer(serializers.ModelSerializer):
    """User activity serializer"""
    user_name = serializers.SerializerMethodField()
    
    class Meta:
        model = UserActivity
        fields = [
            'id', 'user', 'user_name', 'action', 'model_name',
            'object_id', 'timestamp', 'ip_address', 'user_agent'
        ]
        read_only_fields = ['id', 'timestamp']
    
    def get_user_name(self, obj):
        return obj.user.get_full_name() if obj.user else None


class PasswordChangeSerializer(serializers.Serializer):
    """Password change serializer"""
    old_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, data):
        """Validate passwords match"""
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data
    
    def validate_old_password(self, value):
        """Validate old password"""
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class PasswordResetSerializer(serializers.Serializer):
    """Password reset serializer"""
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        """Validate email exists"""
        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("No user found with this email address.")
        return value


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Password reset confirm serializer"""
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, data):
        """Validate passwords match"""
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        return data


class EmailVerificationSerializer(serializers.Serializer):
    """Email verification serializer"""
    token = serializers.UUIDField(required=True)


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    """User profile update serializer"""
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'phone', 'bio',
            'profile_picture'
        ]
    
    def update(self, instance, validated_data):
        """Update user profile"""
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance


class UserOnlineStatusSerializer(serializers.ModelSerializer):
    """Serializer for updating user online status"""
    class Meta:
        model = User
        fields = ['is_online', 'last_activity']
        read_only_fields = ['last_activity']