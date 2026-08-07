# apps/accounts/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponseForbidden
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Q
from django.db import models
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from .models import User, UserActivity, Notification
from .serializers import UserSerializer, UserActivitySerializer, UserCreateSerializer
from tenants.models import Tenant
import uuid
import json
from django.views.decorators.http import require_http_methods
import stripe
from django.utils.text import slugify
from tenants.models import SubscriptionLog
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from django.contrib.admin.views.decorators import staff_member_required
import logging
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import TruncMonth
import datetime



from tenants.models import Tenant, TenantSettings, SubscriptionLog
from accounts.models import User
from inventory.models import Product, StockMovement
from sales.models import Sale, SaleItem
from suppliers.models import PurchaseOrder

from inventory.models import Product, Category, InventoryAlert
from suppliers.models import PurchaseOrder
from sales.models import Sale, SaleItem
from django.db.models import Sum, Count, F
from django.db.models.functions import TruncMonth
import json
import datetime

logger = logging.getLogger(__name__)


def user_has_access(user):
    """Check if user has access to user management"""
    return user.is_authenticated and (user.is_superuser or user.role == 'admin' or user.has_perm('accounts.can_manage_users'))

def user_can_manage_users(user):
    """Check if user can manage users"""
    return user.is_authenticated and (user.is_superuser or user.role == 'admin')


# apps/accounts/views.py - FIXED login_view

def login_view(request):
    """Login page view - supports both AJAX and regular form submissions"""
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if user.is_active:
                # Check if tenant is suspended
                if user.tenant and user.tenant.subscription_status == 'suspended' and not user.is_superuser:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'success': False,
                            'message': 'Your organization account has been suspended. Please contact support.'
                        }, status=400)
                    else:
                        messages.error(request, 'Your organization account has been suspended. Please contact support.')
                        return render(request, 'accounts/login.html', {'title': 'Login - PharmaPro'})
                
                # Check if tenant is expired
                if user.tenant and user.tenant.is_expired() and not user.is_superuser:
                    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                        return JsonResponse({
                            'success': False,
                            'message': 'Your organization subscription has expired. Please contact your administrator to renew.'
                        }, status=400)
                    else:
                        messages.error(request, 'Your organization subscription has expired. Please contact your administrator to renew.')
                        return render(request, 'accounts/login.html', {'title': 'Login - PharmaPro'})
                
                # Login the user
                login(request, user)
                
                # Log activity
                UserActivity.objects.create(
                    user=user,
                    action='User logged in',
                    model_name='User',
                    object_id=str(user.id),
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT')
                )
                
                user.is_online = True
                user.last_activity = timezone.now()
                user.save(update_fields=['is_online', 'last_activity'])
                
                if user.tenant:
                    request.session['tenant_id'] = str(user.tenant.id)
                    request.session['tenant_slug'] = user.tenant.slug
                
                # Get redirect URL based on user role
                redirect_url = get_role_redirect_url(request, user)
                
                # Check if it's an AJAX request
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'redirect_url': redirect_url
                    })
                else:
                    # Regular form submission - redirect
                    return redirect(redirect_url)
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': 'Your account has been deactivated. Please contact support.'
                    }, status=400)
                else:
                    messages.error(request, 'Your account has been deactivated. Please contact support.')
                    return render(request, 'accounts/login.html', {'title': 'Login - PharmaPro'})
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid username or password.'
                }, status=400)
            else:
                messages.error(request, 'Invalid username or password.')
                return render(request, 'accounts/login.html', {'title': 'Login - PharmaPro'})
    
    # GET request - show login page
    context = {
        'title': 'Login - PharmaPro'
    }
    return render(request, 'accounts/login.html', context)


def get_role_redirect_url(request, user):
    """
    Get redirect URL based on user role.
    Uses the URL names from your apps.
    """
    
    # Super Admin - go to tenant management
    if user.is_superuser:
        return '/tenants/manage/'
    
    # Check if user has a tenant
    if not user.tenant:
        return '/accounts/profile/'
    
    # Role-based redirection
    role_redirects = {
        'admin': lambda: f'/accounts/{user.tenant.slug}/dashboard/',  # Admin dashboard
        'manager': lambda: '/inventory/',  # Inventory dashboard (URL pattern name: inventory:dashboard)
        'staff': lambda: '/sales/',  # Sales dashboard (URL pattern name: sales:dashboard)
        'viewer': lambda: '/sales/',  
    }
    
    # Get the redirect URL for the user's role
    redirect_func = role_redirects.get(user.role)
    if redirect_func:
        return redirect_func()
    
    # Default fallback to tenant dashboard
    return f'/accounts/{user.tenant.slug}/dashboard/'


# apps/accounts/views.py - Updated redirect_to_dashboard

def redirect_to_dashboard(request, user, tenant):
    """Helper function to redirect to dashboard based on role"""
    try:
        # Log user activity
        UserActivity.objects.create(
            user=user,
            action='User logged in',
            model_name='User',
            object_id=str(user.id),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
        
        # Update user status
        user.is_online = True
        user.last_activity = timezone.now()
        if tenant:
            user.tenant = tenant
        user.save(update_fields=['is_online', 'last_activity', 'tenant'])
        
        # Set tenant in session
        if tenant:
            request.session['tenant_id'] = str(tenant.id)
            request.session['tenant_slug'] = tenant.slug
        
        # Get redirect URL based on role
        redirect_url = get_role_redirect_url(user)
        
        return JsonResponse({
            'success': True,
            'redirect_url': redirect_url
        })
    except Exception as e:
        print(f"Redirect error: {str(e)}")
        return JsonResponse({
            'success': True,
            'redirect_url': '/accounts/dashboard/'
        })

@login_required
def select_tenant_view(request):
    """View for selecting tenant after login"""
    # Check if user has pending tenant selection
    pending_user_id = request.session.get('pending_user_id')
    if not pending_user_id:
        return redirect('accounts:login')
    
    try:
        user = User.objects.get(id=pending_user_id)
    except User.DoesNotExist:
        return redirect('accounts:login')
    
    if request.method == 'POST':
        tenant_id = request.POST.get('tenant_id')
        try:
            tenant = Tenant.objects.get(id=tenant_id, is_active=True)
            # Log the user in with the selected tenant
            login(request, user)
            user.tenant = tenant
            user.save()
            
            # Clean up session
            del request.session['pending_user_id']
            
            return redirect_to_dashboard(request, user, tenant)
        except Tenant.DoesNotExist:
            messages.error(request, 'Invalid organization selected.')
            return redirect('accounts:select_tenant')
    
    # Get all active tenants the user has access to
    if user.is_superuser:
        tenants = Tenant.objects.filter(is_active=True)
    else:
        tenants = Tenant.objects.filter(id=user.tenant_id, is_active=True)
    
    context = {
        'tenants': tenants,
        'user': user,
        'title': 'Select Organization - PharmaPro'
    }
    return render(request, 'accounts/select_tenant.html', context)




# apps/accounts/views.py - Updated register_view

def send_registration_notification(company_name, admin_email, plan, first_name, last_name, company_phone, company_address):
    """Send notification email to admin about new registration"""
    try:
        subject = f'🔔 New PharmaPro Registration - {company_name}'
        
        # Get plan display name
        plan_names = {
            'free': 'Free Trial',
            'starter': 'Starter (Ugx 29,000/mo)',
            'professional': 'Professional (Ugx 79,000/mo)',
            'enterprise': 'Enterprise (Ugx 199,000/mo)'
        }
        plan_display = plan_names.get(plan, plan.capitalize())
        
        # Build email content
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
                .container {{ max-width: 600px; margin: 0 auto; background: white; border: 1px solid #ddd; padding: 30px; }}
                .header {{ background: #1e293b; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .field {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
                .label {{ font-weight: bold; color: #333; display: inline-block; width: 150px; }}
                .plan-badge {{ display: inline-block; background: #10b981; color: white; padding: 4px 12px; font-size: 12px; font-weight: bold; }}
                .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin:0;">🆕 New Registration</h2>
                </div>
                <div class="content">
                    <p><strong>A new organization has registered on PharmaPro!</strong></p>
                    
                    <div class="field"><span class="label">Company Name:</span> {company_name}</div>
                    <div class="field"><span class="label">Admin Name:</span> {first_name} {last_name}</div>
                    <div class="field"><span class="label">Admin Email:</span> {admin_email}</div>
                    <div class="field"><span class="label">Phone:</span> {company_phone}</div>
                    <div class="field"><span class="label">Address:</span> {company_address}</div>
                    <div class="field"><span class="label">Selected Plan:</span> <span class="plan-badge">{plan_display}</span></div>
                    
                    <div style="margin-top: 20px; background: #f0fdf4; border: 1px solid #86efac; padding: 15px; border-radius: 4px;">
                        <p style="margin:0; color: #166534;"><strong>✅ Action Required:</strong> Please review this registration and activate the account if everything looks correct.</p>
                    </div>
                    
                    <div style="margin-top: 20px;">
                        <p><strong>Next Steps:</strong></p>
                        <ul>
                            <li>Verify the organization details</li>
                            <li>Confirm payment (if applicable)</li>
                            <li>Activate the tenant account</li>
                        </ul>
                    </div>
                </div>
                <div class="footer">
                    <p>PharmaPro - Pharmacy Management Platform</p>
                    <p>This is an automated notification from your PharmaPro system.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        NEW PHARMAPRO REGISTRATION
        
        Company Name: {company_name}
        Admin Name: {first_name} {last_name}
        Admin Email: {admin_email}
        Phone: {company_phone}
        Address: {company_address}
        Selected Plan: {plan_display}
        
        Action Required: Please review this registration and activate the account.
        """
        
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [settings.EMAIL_HOST_USER],  # Send to your configured email
            html_message=html_message,
            fail_silently=False
        )
        return True
        
    except Exception as e:
        print(f"Error sending registration notification: {e}")
        return False


def register_view(request):
    if request.method == 'POST':
        try:
            company_name = request.POST.get('company_name', '').strip()
            slug = request.POST.get('slug', '').strip()
            company_address = request.POST.get('company_address', '').strip()
            company_phone = request.POST.get('company_phone', '').strip()
            company_email = request.POST.get('company_email', '').strip()
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            admin_email = request.POST.get('admin_email', '').strip()
            password = request.POST.get('password', '')
            plan = request.POST.get('plan', 'free').strip()

            print("=== REGISTRATION START ===")
            print(f"Company: {company_name} | Admin Email: {admin_email} | Company Email: {company_email}")

            # === VALIDATIONS ===
            if not all([company_name, admin_email, password, first_name, last_name]):
                messages.error(request, 'Please fill all required fields.')
                return render(request, 'accounts/register.html', {'title': 'Register - PharmaPro', 'plans': get_plan_details()})

            if len(password) < 8:
                messages.error(request, 'Password must be at least 8 characters.')
                return render(request, 'accounts/register.html', {'title': 'Register - PharmaPro', 'plans': get_plan_details()})

            # CRITICAL: Emails must match
            if company_email.lower() != admin_email.lower():
                messages.error(request, 'Organization email must match Admin email.')
                return render(request, 'accounts/register.html', {'title': 'Register - PharmaPro', 'plans': get_plan_details()})

            if User.objects.filter(email=admin_email).exists():
                messages.error(request, 'Email already exists. Please use a different email or login.')
                return render(request, 'accounts/register.html', {'title': 'Register - PharmaPro', 'plans': get_plan_details()})

            # Slug handling
            if not slug:
                slug = slugify(company_name)
                counter = 1
                original = slug
                while Tenant.objects.filter(slug=slug).exists():
                    slug = f"{original}-{counter}"
                    counter += 1

            # === CREATE ===
            with transaction.atomic():
                user = User.objects.create_user(
                    username=admin_email,
                    email=admin_email,
                    first_name=first_name,
                    last_name=last_name,
                    password=password,
                    role='admin',
                    is_active=True,
                )

                tenant = Tenant.objects.create(
                    name=company_name,
                    slug=slug,
                    company_name=company_name,
                    company_address=company_address,
                    company_phone=company_phone,
                    company_email=company_email,
                    plan=plan,
                    subscription_status='trial',
                    created_by=user,
                    trial_end_date=timezone.now() + timedelta(days=14),
                )

                user.tenant = tenant
                user.save(update_fields=['tenant'])

            # Send verification email
            try:
                user.send_verification_email(request)
                print(f"Verification email sent to {user.email}")
            except Exception as e:
                print(f"Failed to send verification email: {e}")

            # ===== SEND NOTIFICATION EMAIL TO ADMIN =====
            # This is where you put the notification - right after successful registration
            try:
                send_registration_notification(
                    company_name=company_name,
                    admin_email=admin_email,
                    plan=plan,
                    first_name=first_name,
                    last_name=last_name,
                    company_phone=company_phone,
                    company_address=company_address
                )
                print("Registration notification sent to admin")
            except Exception as e:
                print(f"Failed to send registration notification: {e}")

            print("✅ Registration successful!")

            # Check if it's an AJAX request
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Registration successful! Please check your email for verification.',
                    'redirect_url': '/accounts/login/'
                })
            else:
                # Regular form submission - redirect with success message
                messages.success(request, 'Registration successful! Please check your email for verification.')
                return redirect('accounts:login')

        except Exception as e:
            import traceback
            traceback.print_exc()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'message': str(e)}, status=400)
            else:
                messages.error(request, f'Registration failed: {str(e)}')
                return render(request, 'accounts/register.html', {'title': 'Register - PharmaPro', 'plans': get_plan_details()})

    # GET
    context = {
        'title': 'Register - PharmaPro',
        'plans': get_plan_details()
    }
    return render(request, 'accounts/register.html', context)


# apps/accounts/views.py - Add this view

@staff_member_required
def superuser_tenant_create_view(request):
    """Superuser view to create a new tenant/organization internally"""
    
    if request.method == 'POST':
        try:
            # Get form data
            company_name = request.POST.get('company_name', '').strip()
            slug = request.POST.get('slug', '').strip()
            company_address = request.POST.get('company_address', '').strip()
            company_phone = request.POST.get('company_phone', '').strip()
            company_email = request.POST.get('company_email', '').strip()
            
            admin_first_name = request.POST.get('admin_first_name', '').strip()
            admin_last_name = request.POST.get('admin_last_name', '').strip()
            admin_email = request.POST.get('admin_email', '').strip()
            admin_password = request.POST.get('admin_password', '')
            
            plan = request.POST.get('plan', 'free').strip()
            subscription_status = request.POST.get('subscription_status', 'trial')
            subscription_days = int(request.POST.get('subscription_days', 14))
            
            # Validate required fields
            if not all([company_name, company_email, admin_first_name, admin_last_name, admin_email]):
                messages.error(request, 'Please fill all required fields.')
                return redirect('accounts:superuser_tenant_create')
            
            if admin_password and len(admin_password) < 8:
                messages.error(request, 'Password must be at least 8 characters.')
                return redirect('accounts:superuser_tenant_create')
            
            # Check if email already exists
            if User.objects.filter(email=admin_email).exists():
                messages.error(request, f'User with email "{admin_email}" already exists.')
                return redirect('accounts:superuser_tenant_create')
            
            # Check if company email already used
            if Tenant.objects.filter(company_email=company_email).exists():
                messages.error(request, f'Organization with email "{company_email}" already exists.')
                return redirect('accounts:superuser_tenant_create')
            
            # Generate slug if not provided
            if not slug:
                slug = slugify(company_name)
                original_slug = slug
                counter = 1
                while Tenant.objects.filter(slug=slug).exists():
                    slug = f"{original_slug}-{counter}"
                    counter += 1
            
            # Generate password if not provided
            if not admin_password:
                org_clean = ''.join(e for e in company_name if e.isalnum()).lower()
                admin_password = f"{org_clean}@{timezone.now().year}"
            
            # Create tenant and admin user in transaction
            with transaction.atomic():
                # Create the admin user first
                admin_user = User.objects.create_user(
                    username=admin_email,
                    email=admin_email,
                    password=admin_password,
                    first_name=admin_first_name,
                    last_name=admin_last_name,
                    role='admin',
                    is_active=True,
                    email_verified=True,
                )
                
                # Calculate dates
                now = timezone.now()
                if subscription_status == 'trial':
                    trial_end = now + timedelta(days=subscription_days)
                    subscription_end = None
                else:
                    trial_end = None
                    subscription_end = now + timedelta(days=subscription_days)
                
                # Create the tenant
                tenant = Tenant.objects.create(
                    name=company_name,
                    slug=slug,
                    company_name=company_name,
                    company_address=company_address,
                    company_phone=company_phone,
                    company_email=company_email,
                    plan=plan,
                    subscription_status=subscription_status,
                    created_by=admin_user,
                    trial_start_date=now if subscription_status == 'trial' else None,
                    trial_end_date=trial_end,
                    subscription_start_date=now if subscription_status != 'trial' else None,
                    subscription_end_date=subscription_end,
                    is_active=True,
                )
                
                # Assign tenant to admin user
                admin_user.tenant = tenant
                admin_user.save(update_fields=['tenant'])
                
                # Log the creation
                UserActivity.objects.create(
                    user=request.user,
                    action=f'Created organization: {company_name}',
                    model_name='Tenant',
                    object_id=str(tenant.id),
                    ip_address=request.META.get('REMOTE_ADDR'),
                    user_agent=request.META.get('HTTP_USER_AGENT'),
                    details={
                        'tenant_id': str(tenant.id),
                        'admin_email': admin_email,
                        'plan': plan,
                        'status': subscription_status
                    }
                )
            
            # Send welcome email to admin
            try:
                send_user_welcome_email(admin_user, admin_password)
            except Exception as e:
                logger.error(f"Failed to send welcome email: {e}")
            
            messages.success(
                request,
                f'Organization "{company_name}" created successfully! '
                f'Admin: {admin_email}, Password: {admin_password}'
            )
            return redirect('tenants:detail', tenant_id=tenant.id)
            
        except Exception as e:
            messages.error(request, f'Error creating organization: {str(e)}')
            logger.error(f"Tenant creation error: {str(e)}")
            return redirect('accounts:superuser_tenant_create')
    
    # GET request - show form
    context = {
        'plans': get_plan_details(),
        'status_choices': [
            ('trial', 'Trial'),
            ('active', 'Active'),
            ('suspended', 'Suspended'),
            ('cancelled', 'Cancelled'),
        ],
        'title': 'Create Organization - Super Admin'
    }
    return render(request, 'accounts/superuser_tenant_create.html', context)




def get_plan_details():
    """Get plan details with pricing in UGX"""
    return {
        'free': {
            'name': 'Free Trial',
            'price': 0,
            'price_display': 'Free',
            'currency': 'UGX',
            'features': [
                '5 Users',
                '100 Products',
                '500 Sales Records',
                '14-Day Trial'
            ],
            'recommended': False
        },
        'starter': {
            'name': 'Starter',
            'price': 29000,
            'price_display': 'Ugx 29,000',
            'currency': 'UGX',
            'features': [
                '5 Users',
                '100 Products',
                '500 Sales Records',
                'Email Support'
            ],
            'recommended': False
        },
        'professional': {
            'name': 'Professional',
            'price': 79000,
            'price_display': 'Ugx 79,000',
            'currency': 'UGX',
            'features': [
                '25 Users',
                'Unlimited Products',
                'Unlimited Sales',
                'Advanced Reports',
                'Priority Support'
            ],
            'recommended': True
        },
        'enterprise': {
            'name': 'Enterprise',
            'price': 199000,
            'price_display': 'Ugx 199,000',
            'currency': 'UGX',
            'features': [
                'Unlimited Users',
                'Unlimited Products',
                'Unlimited Sales',
                'Custom Reports',
                'Dedicated Support',
                'API Access'
            ],
            'recommended': False
        }
    }


@login_required
def logout_view(request):
    """Logout view"""
    # Update user status
    if request.user.is_authenticated:
        request.user.is_online = False
        request.user.save(update_fields=['is_online'])
        
        # Log activity
        UserActivity.objects.create(
            user=request.user,
            action='User logged out',
            model_name='User',
            object_id=str(request.user.id),
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT')
        )
    
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('accounts:login')


# apps/accounts/views.py - Updated profile_view

@login_required
def profile_view(request):
    """User profile view"""
    if request.method == 'POST':
        user = request.user
        username = request.POST.get('username')
        first_name = request.POST.get('first_name', user.first_name)
        last_name = request.POST.get('last_name', user.last_name)
        phone = request.POST.get('phone', user.phone)
        bio = request.POST.get('bio', user.bio)
        
        # Validate username if provided
        if username:
            username = username.strip()
            # Check if username is taken by another user
            if User.objects.exclude(id=user.id).filter(username=username).exists():
                # Check if it's an AJAX request
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'message': 'This username is already taken. Please choose another.'
                    }, status=400)
                messages.error(request, 'This username is already taken. Please choose another.')
                return redirect('accounts:profile')
            user.username = username
        
        user.first_name = first_name
        user.last_name = last_name
        user.phone = phone
        user.bio = bio
        
        if request.FILES.get('profile_picture'):
            user.profile_picture = request.FILES.get('profile_picture')
        
        user.save()
        
        # Check if it's an AJAX request
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Profile updated successfully!',
                'user': {
                    'full_name': user.get_full_name(),
                    'username': user.username,
                    'email': user.email,
                    'phone': user.phone,
                    'bio': user.bio,
                    'profile_picture_url': user.profile_picture.url if user.profile_picture else None
                }
            })
        
        messages.success(request, 'Profile updated successfully!')
        return redirect('accounts:profile')
    
    context = {
        'user': request.user,
        'title': 'Profile - PharmaPro'
    }
    return render(request, 'accounts/profile.html', context)



@login_required
def check_username_view(request):
    """Check if username is available"""
    username = request.GET.get('username', '').strip()
    
    if len(username) < 3:
        return JsonResponse({
            'exists': True,
            'message': 'Username must be at least 3 characters'
        })
    
    # Check if username exists (excluding current user)
    exists = User.objects.exclude(id=request.user.id).filter(username=username).exists()
    
    return JsonResponse({
        'exists': exists,
        'message': 'Username is already taken' if exists else 'Username is available'
    })


@login_required
def profile_update_view(request):
    """Update user profile via AJAX"""
    if request.method == 'POST':
        user = request.user
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.phone = request.POST.get('phone', user.phone)
        user.bio = request.POST.get('bio', user.bio)
        
        if request.FILES.get('profile_picture'):
            user.profile_picture = request.FILES.get('profile_picture')
        
        user.save()
        return JsonResponse({
            'success': True,
            'message': 'Profile updated successfully!',
            'user': {
                'full_name': user.get_full_name(),
                'email': user.email,
                'phone': user.phone,
                'bio': user.bio,
                'profile_picture_url': user.profile_picture.url if user.profile_picture else None
            }
        })
    
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

def access_denied_view(request):
    """Access denied page"""
    context = {
        'title': 'Access Denied - PharmaPro'
    }
    return render(request, 'accounts/access_denied.html', context)



@login_required
def user_list_view(request):
    """List all users for the current tenant with online status"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    tenant = request.user.tenant
    users = User.objects.filter(tenant=tenant)
    
    # Get online users count
    online_users = users.filter(is_online=True)
    
    # Get active users count
    active_users = users.filter(is_active=True)
    
    # Get admin users count (role = 'admin' or 'super_admin')
    admin_users = users.filter(role__in=['admin', 'super_admin'])
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(username__icontains=search_query)
        )
    
    # Filter by role
    role_filter = request.GET.get('role', '')
    if role_filter:
        users = users.filter(role=role_filter)
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        if status_filter == 'online':
            users = users.filter(is_online=True)
        elif status_filter == 'offline':
            users = users.filter(is_online=False)
        else:
            is_active = status_filter == 'active'
            users = users.filter(is_active=is_active)
    
    # Pagination
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page', 1)
    users_page = paginator.get_page(page_number)
    
    # Get available roles for this user (excluding super_admin)
    available_roles = [role for role in User.ROLE_CHOICES if role[0] != 'super_admin']
    
    context = {
        'users': users_page,
        'online_users': online_users,
        'online_count': online_users.count(),
        'total_users': users.count(),
        'active_count': active_users.count(),
        'admin_count': admin_users.count(),
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'roles': available_roles,  # Exclude super_admin
        'title': 'Users - PharmaPro'
    }
    return render(request, 'accounts/users.html', context)



@login_required
def user_create_view(request):
    """Create a new user with email notification"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    # Get the tenant from the user
    tenant = request.user.tenant
    
    # If user doesn't have a tenant, redirect with error
    if not tenant:
        messages.error(request, 'You do not have an organization assigned to your account.')
        return redirect('accounts:profile')
    
    # Check if tenant has reached user limit
    from tenants.utils import check_plan_limit, get_plan_limit, get_current_usage
    
    if not check_plan_limit(tenant, 'max_users'):
        current_users = get_current_usage(tenant, 'max_users')
        max_users = get_plan_limit(tenant, 'max_users')
        messages.error(
            request, 
            f'User limit reached! You have {current_users} users and your plan allows only {max_users} users. '
            f'Please upgrade your plan to add more users.'
        )
        return redirect('accounts:user_list')
    
    if request.method == 'POST':
        try:
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            role = request.POST.get('role', 'staff')
            password = request.POST.get('password')
            phone = request.POST.get('phone', '')
            
            # Validate
            if not all([email, first_name, last_name]):
                messages.error(request, 'Please fill all required fields.')
                return redirect('accounts:user_create')
            
            if User.objects.filter(email=email).exists():
                messages.error(request, 'A user with this email already exists.')
                return redirect('accounts:user_create')
            
            # Generate default password if not provided
            if not password:
                org_name = tenant.company_name or tenant.name
                org_name_clean = ''.join(e for e in org_name if e.isalnum()).lower()
                current_year = timezone.now().year
                password = f"{org_name_clean}@{current_year}"
            
            # Create user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role,
                phone=phone,
                tenant=tenant,
                can_view=True,
                email_verified=True,
                is_active=True
            )
            
            # Set permissions
            user.can_create = request.POST.get('can_create') == 'on'
            user.can_edit = request.POST.get('can_edit') == 'on'
            user.can_delete = request.POST.get('can_delete') == 'on'
            user.can_view = True
            user.save()
            
            # Send welcome email with login credentials
            send_user_welcome_email(user, password)
            
            # Get updated user count
            current_users = get_current_usage(tenant, 'max_users')
            max_users = get_plan_limit(tenant, 'max_users')
            
            messages.success(
                request, 
                f'User {user.get_full_name()} created successfully! Password: {password} '
                f'({current_users}/{max_users} users used)'
            )
            return redirect('accounts:user_list')
            
        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
            return redirect('accounts:user_create')
    
    # Get available roles for this user (excluding super_admin)
    available_roles = [role for role in User.ROLE_CHOICES if role[0] != 'super_admin']
    
    # Generate a default password for display
    org_name = tenant.company_name or tenant.name
    org_name_clean = ''.join(e for e in org_name if e.isalnum()).lower()
    current_year = timezone.now().year
    default_password = f"{org_name_clean}@{current_year}"
    
    # Get current usage
    current_users = get_current_usage(tenant, 'max_users')
    max_users = get_plan_limit(tenant, 'max_users')
    can_add_more = check_plan_limit(tenant, 'max_users')
    
    context = {
        'title': 'Create User - PharmaPro',
        'roles': available_roles,
        'default_password': default_password,
        'tenant': tenant,
        'current_users': current_users,
        'max_users': max_users,
        'can_add_more': can_add_more,
    }
    return render(request, 'accounts/user_create.html', context)


@login_required
def user_edit_view(request, user_id):
    """Edit user details including password"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    user = get_object_or_404(User, id=user_id, tenant=request.user.tenant)
    
    if request.method == 'POST':
        try:
            user.first_name = request.POST.get('first_name', user.first_name)
            user.last_name = request.POST.get('last_name', user.last_name)
            user.role = request.POST.get('role', user.role)
            user.phone = request.POST.get('phone', user.phone)
            
            # Update permissions
            user.can_create = request.POST.get('can_create') == 'on'
            user.can_edit = request.POST.get('can_edit') == 'on'
            user.can_delete = request.POST.get('can_delete') == 'on'
            
            # Update password if provided
            new_password = request.POST.get('password')
            if new_password:
                if len(new_password) < 8:
                    messages.error(request, 'Password must be at least 8 characters long.')
                    return redirect('accounts:user_edit', user_id=user_id)
                user.set_password(new_password)
                # Send password change notification
                send_password_changed_email(user, new_password)
            
            user.save()
            
            messages.success(request, f'User {user.get_full_name()} updated successfully!')
            return redirect('accounts:user_list')
            
        except Exception as e:
            messages.error(request, f'Error updating user: {str(e)}')
            return redirect('accounts:user_edit', user_id=user_id)
    
    # Get available roles for this user (excluding super_admin)
    available_roles = [role for role in User.ROLE_CHOICES if role[0] != 'super_admin']
    
    context = {
        'user': user,
        'roles': available_roles,
        'title': 'Edit User - PharmaPro'
    }
    return render(request, 'accounts/user_edit.html', context)

# apps/accounts/views.py - Update user_edit_view

@login_required
def tenant_user_edit_view(request, user_id):
    """Edit user details including password"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    # Convert string to UUID if needed
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        messages.error(request, 'Invalid user ID format.')
        return redirect('accounts:user_list')
    
    # Get the user
    try:
        user = User.objects.get(id=user_id, tenant=request.user.tenant)
    except User.DoesNotExist:
        messages.error(request, 'User not found or you do not have permission to edit this user.')
        return redirect('accounts:user_list')
    
    if request.method == 'POST':
        try:
            user.first_name = request.POST.get('first_name', user.first_name)
            user.last_name = request.POST.get('last_name', user.last_name)
            user.role = request.POST.get('role', user.role)
            user.phone = request.POST.get('phone', user.phone)
            
            # Update permissions
            user.can_create = request.POST.get('can_create') == 'on'
            user.can_edit = request.POST.get('can_edit') == 'on'
            user.can_delete = request.POST.get('can_delete') == 'on'
            
            # Update password if provided
            new_password = request.POST.get('password')
            if new_password:
                if len(new_password) < 8:
                    messages.error(request, 'Password must be at least 8 characters long.')
                    return redirect('accounts:user_edit', user_id=user_id)
                user.set_password(new_password)
                # Send password change notification
                send_password_changed_email(user, new_password)
            
            user.save()
            
            messages.success(request, f'User {user.get_full_name()} updated successfully!')
            return redirect('accounts:user_list')
            
        except Exception as e:
            messages.error(request, f'Error updating user: {str(e)}')
            return redirect('accounts:user_edit', user_id=user_id)
    
    # Get available roles for this user (excluding super_admin)
    available_roles = [role for role in User.ROLE_CHOICES if role[0] != 'super_admin']
    
    context = {
        'user': user,
        'roles': available_roles,
        'title': 'Edit User - PharmaPro'
    }
    return render(request, 'accounts/user_edit.html', context)


# apps/accounts/views.py - Update user_delete_view

@login_required
def user_delete_view(request, user_id):
    """Delete a user"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return JsonResponse({
            'success': False, 
            'error': 'You do not have permission to delete users.'
        }, status=403)
    
    user = get_object_or_404(User, id=user_id, tenant=request.user.tenant)
    
    if request.method == 'POST':
        try:
            # Don't allow deleting self
            if user.id == request.user.id:
                return JsonResponse({
                    'success': False, 
                    'error': 'You cannot delete your own account.'
                }, status=400)
            
            # Don't allow deleting other admins (only super admin can)
            if user.role == 'admin' and not request.user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot delete another organization admin.'
                }, status=403)
            
            user_name = user.get_full_name()
            user.delete()
            
            # Return success with redirect URL
            return JsonResponse({
                'success': True, 
                'message': f'User {user_name} deleted successfully!',
                'redirect_url': reverse('accounts:user_list')  # Add redirect URL
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    context = {
        'user': user,
        'title': 'Delete User - PharmaPro'
    }
    return render(request, 'accounts/user_delete.html', context)


# apps/accounts/views.py - Update user_delete_view

@login_required
def tenant_user_delete_view(request, user_id):
    """Delete a user"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return JsonResponse({
            'success': False, 
            'error': 'You do not have permission to delete users.'
        }, status=403)
    
    # Convert string to UUID if needed
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'error': 'Invalid user ID format.'
        }, status=400)
    
    # Get the user
    try:
        user = User.objects.get(id=user_id, tenant=request.user.tenant)
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'User not found.'
        }, status=404)
    
    if request.method == 'POST':
        try:
            # Don't allow deleting self
            if user.id == request.user.id:
                return JsonResponse({
                    'success': False, 
                    'error': 'You cannot delete your own account.'
                }, status=400)
            
            # Don't allow deleting other admins (only super admin can)
            if user.role == 'admin' and not request.user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot delete another organization admin.'
                }, status=403)
            
            user_name = user.get_full_name()
            user.delete()
            
            # Return success with redirect URL
            return JsonResponse({
                'success': True, 
                'message': f'User {user_name} deleted successfully!',
                'redirect_url': reverse('accounts:user_list')
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    context = {
        'user': user,
        'title': 'Delete User - PharmaPro'
    }
    return render(request, 'accounts/user_delete.html', context)


def get_quick_filter_dates(quick_filter):
    """Get date filter for quick filter options"""
    now = timezone.now().date()
    date_filter = {}
    
    if quick_filter == 'today':
        date_filter['sale_date__date'] = now
    elif quick_filter == 'yesterday':
        date_filter['sale_date__date'] = now - timedelta(days=1)
    elif quick_filter == 'week':
        start = now - timedelta(days=now.weekday())
        date_filter['sale_date__date__gte'] = start
        date_filter['sale_date__date__lte'] = now
    elif quick_filter == 'month':
        start = now.replace(day=1)
        date_filter['sale_date__date__gte'] = start
        date_filter['sale_date__date__lte'] = now
    elif quick_filter == 'quarter':
        quarter = (now.month - 1) // 3
        start = now.replace(month=quarter * 3 + 1, day=1)
        date_filter['sale_date__date__gte'] = start
        date_filter['sale_date__date__lte'] = now
    elif quick_filter == 'year':
        start = now.replace(month=1, day=1)
        date_filter['sale_date__date__gte'] = start
        date_filter['sale_date__date__lte'] = now
    
    return date_filter


# apps/accounts/views.py - Update tenant_dashboard_view

@login_required
def tenant_dashboard_view(request, tenant_slug):
    """Main dashboard for tenant with filtering and charts"""
    tenant = get_object_or_404(Tenant, slug=tenant_slug)
    
    # Check if user has access to this tenant
    if not request.user.is_superuser and request.user.tenant != tenant:
        return render(request, 'accounts/access_denied.html', {
            'title': 'Access Denied - PharmaPro'
        })
    
    if not tenant:
        messages.error(request, 'You do not have an organization assigned.')
        return redirect('accounts:profile')
    
    # Get filter parameters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    quick_filter = request.GET.get('quick_filter', '')
    
    # Build date filter for sales
    date_filter = {}
    sale_date_filter = {}
    po_date_filter = {}
    
    if date_from:
        try:
            date_from_obj = datetime.datetime.strptime(date_from, '%Y-%m-%d').date()
            date_filter['sale_date__date__gte'] = date_from_obj
            sale_date_filter['sale_date__date__gte'] = date_from_obj
            po_date_filter['created_at__date__gte'] = date_from_obj
        except ValueError:
            pass
    if date_to:
        try:
            date_to_obj = datetime.datetime.strptime(date_to, '%Y-%m-%d').date()
            date_filter['sale_date__date__lte'] = date_to_obj
            sale_date_filter['sale_date__date__lte'] = date_to_obj
            po_date_filter['created_at__date__lte'] = date_to_obj
        except ValueError:
            pass
    
    # If quick filter is set but no dates, apply quick filter
    if quick_filter and not date_from and not date_to:
        date_filter = get_quick_filter_dates(quick_filter)
        sale_date_filter = date_filter.copy()
        po_date_filter = {}
        if 'sale_date__date' in date_filter:
            po_date_filter['created_at__date'] = date_filter['sale_date__date']
        if 'sale_date__date__gte' in date_filter:
            po_date_filter['created_at__date__gte'] = date_filter['sale_date__date__gte']
        if 'sale_date__date__lte' in date_filter:
            po_date_filter['created_at__date__lte'] = date_filter['sale_date__date__lte']
    
    # === STATISTICS ===
    total_products = Product.objects.filter(tenant=tenant).count()
    total_users = User.objects.filter(tenant=tenant).count()
    online_users = User.objects.filter(tenant=tenant, is_online=True).count()
    
    # === SALES WITH ROLE-BASED FILTERING ===
    sales_qs = Sale.objects.filter(tenant=tenant)
    
    if request.user.role == 'staff':
        sales_qs = sales_qs.filter(created_by=request.user)
    
    if date_filter:
        sales_qs = sales_qs.filter(**date_filter)
    
    total_sales = sales_qs.count()
    filtered_sales_total = sales_qs.aggregate(total=Sum('total_amount'))['total'] or 0
    filtered_sales_count = sales_qs.count()
    
    # === MONTHLY SALES ===
    monthly_sales_qs = Sale.objects.filter(tenant=tenant)
    if request.user.role == 'staff':
        monthly_sales_qs = monthly_sales_qs.filter(created_by=request.user)
    
    monthly_sales_qs = monthly_sales_qs.annotate(
        month=TruncMonth('sale_date')
    ).values('month').annotate(
        total=Sum('total_amount')
    ).order_by('month')
    
    monthly_sales_list = []
    for item in monthly_sales_qs:
        if item['month']:
            monthly_sales_list.append({
                'month': item['month'].strftime('%Y-%m-%d'),
                'total': float(item['total']) if item['total'] else 0
            })
    
    monthly_sales_json = json.dumps(monthly_sales_list)
    
    # === PRODUCT STATUS ===
    status_distribution = []
    for item in Product.objects.filter(tenant=tenant).values('status').annotate(count=Count('id')):
        status_distribution.append({
            'status': item['status'],
            'count': item['count']
        })
    
    # === TOP 5 PRODUCTS ===
    sale_items_qs = SaleItem.objects.filter(sale__tenant=tenant)
    
    if sale_date_filter:
        sale_item_filter = {}
        if 'sale_date__date__gte' in sale_date_filter:
            sale_item_filter['sale__sale_date__date__gte'] = sale_date_filter['sale_date__date__gte']
        if 'sale_date__date__lte' in sale_date_filter:
            sale_item_filter['sale__sale_date__date__lte'] = sale_date_filter['sale_date__date__lte']
        if 'sale_date__date' in sale_date_filter:
            sale_item_filter['sale__sale_date__date'] = sale_date_filter['sale_date__date']
        
        if sale_item_filter:
            sale_items_qs = sale_items_qs.filter(**sale_item_filter)
    
    top_products_qs = sale_items_qs.values('product__name').annotate(
        total_sold=Sum('quantity')
    ).order_by('-total_sold')[:5]
    
    top_products = []
    for item in top_products_qs:
        top_products.append({
            'product__name': item['product__name'] or 'Unknown Product',
            'total_sold': float(item['total_sold']) if item['total_sold'] else 0
        })
    
    # === PURCHASE ORDERS ===
    po_qs = PurchaseOrder.objects.filter(tenant=tenant)
    
    if request.user.role == 'staff':
        po_qs = po_qs.filter(created_by=request.user)
    
    if po_date_filter:
        po_qs = po_qs.filter(**po_date_filter)
    
    po_status_distribution = []
    for item in po_qs.values('status').annotate(count=Count('id')):
        po_status_distribution.append({
            'status': item['status'],
            'count': item['count']
        })
    
    # === RECENT PURCHASE ORDERS ===
    recent_pos_qs = PurchaseOrder.objects.filter(tenant=tenant)
    if request.user.role == 'staff':
        recent_pos_qs = recent_pos_qs.filter(created_by=request.user)
    if po_date_filter:
        recent_pos_qs = recent_pos_qs.filter(**po_date_filter)
    recent_pos = recent_pos_qs.select_related('supplier').order_by('-created_at')[:10]
    
    # === SALES BY PAYMENT STATUS ===
    sales_by_status_qs = Sale.objects.filter(tenant=tenant)
    if request.user.role == 'staff':
        sales_by_status_qs = sales_by_status_qs.filter(created_by=request.user)
    if date_filter:
        sales_by_status_qs = sales_by_status_qs.filter(**date_filter)
    
    sales_by_status = []
    for item in sales_by_status_qs.values('payment_status').annotate(count=Count('id')):
        sales_by_status.append({
            'payment_status': item['payment_status'],
            'count': item['count']
        })
    
    # === RECENT SALES ===
    recent_sales_qs = Sale.objects.filter(tenant=tenant)
    if request.user.role == 'staff':
        recent_sales_qs = recent_sales_qs.filter(created_by=request.user)
    recent_sales = recent_sales_qs.select_related('created_by').order_by('-sale_date')[:10]
    
    # === LOW STOCK ===
    low_stock_products = Product.objects.filter(
        tenant=tenant,
        quantity__lte=F('reorder_point'),
        is_active=True
    )[:10]
    
    # === LOW STOCK COUNT ===
    low_stock = Product.objects.filter(
        tenant=tenant, 
        quantity__lte=F('reorder_point'),
        quantity__gt=0
    ).count()
    
    # === OUT OF STOCK COUNT ===
    out_of_stock = Product.objects.filter(tenant=tenant, quantity=0).count()
    
    # === TOTAL CATEGORIES ===
    total_categories = Category.objects.filter(tenant=tenant).count()
    
    # ===== INVENTORY ALERTS - ONLY UNRESOLVED =====
    from inventory.models import InventoryAlert
    
    # Get only UNRESOLVED alerts (is_resolved=False)
    unresolved_alerts = InventoryAlert.objects.filter(
        tenant=tenant,
        is_resolved=False
    ).order_by('-created_at')[:10]
    
    # Count unresolved alerts
    active_alerts_count = InventoryAlert.objects.filter(
        tenant=tenant,
        is_resolved=False
    ).count()
    
    # Recent alerts (unread) for compatibility
    recent_alerts = InventoryAlert.objects.filter(
        tenant=tenant,
        is_read=False,
        is_resolved=False  # Only unresolved
    ).order_by('-created_at')[:5]
    
    # === EXPIRING PRODUCTS ===
    thirty_days_from_now = timezone.now().date() + datetime.timedelta(days=30)
    expiring_products = Product.objects.filter(
        tenant=tenant,
        expiry_date__isnull=False,
        expiry_date__lte=thirty_days_from_now,
        expiry_date__gte=timezone.now().date(),
        quantity__gt=0
    ).select_related('category', 'unit').order_by('expiry_date')[:10]
    
    # === FILTER DISPLAY ===
    filter_display = "All Time"
    if date_from and date_to:
        filter_display = f"{date_from} to {date_to}"
    elif date_from:
        filter_display = f"From {date_from}"
    elif date_to:
        filter_display = f"Until {date_to}"
    elif quick_filter:
        filter_map = {
            'today': 'Today',
            'yesterday': 'Yesterday',
            'week': 'This Week',
            'month': 'This Month',
            'quarter': 'This Quarter',
            'year': 'This Year'
        }
        filter_display = filter_map.get(quick_filter, 'Custom Range')
    
    context = {
        'tenant': tenant,
        'total_products': total_products,
        'total_sales': total_sales,
        'total_users': total_users,
        'online_users': online_users,
        'recent_sales': recent_sales,
        'low_stock_products': low_stock_products,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'total_categories': total_categories,
        'filtered_sales_total': filtered_sales_total,
        'filtered_sales_count': filtered_sales_count,
        'today_sales': filtered_sales_total,
        'today_count': filtered_sales_count,
        'monthly_sales': monthly_sales_json,
        'monthly_sales_count': len(monthly_sales_list),
        'status_distribution': status_distribution,
        'top_products': top_products,
        'po_status_distribution': po_status_distribution,
        'sales_by_status': sales_by_status,
        'recent_pos': recent_pos,
        'date_from': date_from,
        'date_to': date_to,
        'quick_filter': quick_filter,
        'filter_display': filter_display,
        'user_role': request.user.role,
        'is_staff': request.user.role == 'staff',
        'has_products': total_products > 0,
        'has_sales': total_sales > 0,
        'has_pos': PurchaseOrder.objects.filter(tenant=tenant).exists(),
        # ===== ALERT DATA - ONLY UNRESOLVED =====
        'unresolved_alerts': unresolved_alerts,  # Only unresolved alerts
        'active_alerts_count': active_alerts_count,
        'recent_alerts': recent_alerts,
        'expiring_products': expiring_products,
        'title': f'{tenant.name} Dashboard - PharmaPro'
    }
    return render(request, 'accounts/dashboard.html', context)


@login_required
def change_password_view(request):
    """Change user password via AJAX"""
    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            
            current_password = data.get('current_password')
            new_password = data.get('new_password')
            confirm_password = data.get('confirm_password')
            
            # Validate
            if not all([current_password, new_password, confirm_password]):
                return JsonResponse({
                    'success': False,
                    'message': 'All fields are required.'
                }, status=400)
            
            # Check current password
            user = request.user
            if not user.check_password(current_password):
                return JsonResponse({
                    'success': False,
                    'message': 'Current password is incorrect.'
                }, status=400)
            
            # Check new password length
            if len(new_password) < 8:
                return JsonResponse({
                    'success': False,
                    'message': 'Password must be at least 8 characters long.'
                }, status=400)
            
            # Check passwords match
            if new_password != confirm_password:
                return JsonResponse({
                    'success': False,
                    'message': 'New passwords do not match.'
                }, status=400)
            
            # Change password
            user.set_password(new_password)
            user.save()
            
            # Log activity
            UserActivity.objects.create(
                user=user,
                action='Password changed',
                model_name='User',
                object_id=str(user.id),
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Password changed successfully.'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'message': 'Invalid request format.'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': str(e)
            }, status=400)
    
    return JsonResponse({
        'success': False,
        'message': 'Invalid request method.'
    }, status=405)

@login_required
def user_toggle_active_view(request, user_id):
    """Toggle user active status"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to manage users.'
        }, status=403)
    
    user = get_object_or_404(User, id=user_id, tenant=request.user.tenant)
    
    if request.method == 'POST':
        try:
            # Don't allow deactivating self
            if user.id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot change your own status.'
                }, status=400)
            
            # Don't allow deactivating other admins (only super admin can)
            if user.role == 'admin' and not request.user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot change the status of another organization admin.'
                }, status=403)
            
            user.is_active = not user.is_active
            if not user.is_active:
                user.is_online = False
            user.save(update_fields=['is_active', 'is_online'])
            
            return JsonResponse({
                'success': True,
                'message': f"User {'activated' if user.is_active else 'deactivated'} successfully",
                'is_active': user.is_active,
                'is_online': user.is_online
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


# apps/accounts/views.py - Update user_toggle_active_view

@login_required
def tenant_user_toggle_active_view(request, user_id):
    """Toggle user active status"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to manage users.'
        }, status=403)
    
    # Convert string to UUID if needed
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
    except (ValueError, TypeError):
        return JsonResponse({
            'success': False,
            'error': 'Invalid user ID format.'
        }, status=400)
    
    # Get the user
    try:
        user = User.objects.get(id=user_id, tenant=request.user.tenant)
    except User.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'User not found.'
        }, status=404)
    
    if request.method == 'POST':
        try:
            # Don't allow deactivating self
            if user.id == request.user.id:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot change your own status.'
                }, status=400)
            
            # Don't allow deactivating other admins (only super admin can)
            if user.role == 'admin' and not request.user.is_superuser:
                return JsonResponse({
                    'success': False,
                    'error': 'You cannot change the status of another organization admin.'
                }, status=403)
            
            user.is_active = not user.is_active
            if not user.is_active:
                user.is_online = False
            user.save(update_fields=['is_active', 'is_online'])
            
            return JsonResponse({
                'success': True,
                'message': f"User {'activated' if user.is_active else 'deactivated'} successfully",
                'is_active': user.is_active,
                'is_online': user.is_online
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)




@login_required
def settings_view(request):
    """User settings view"""
    tenant = request.user.tenant
    
    # If user has no tenant, redirect to profile
    if not tenant:
        messages.error(request, 'You do not have an organization associated with your account.')
        return redirect('accounts:profile')
    
    # Import necessary models
    from tenants.models import TenantSettings
    from accounts.models import User
    from decimal import Decimal
    
    # Get or create settings
    try:
        settings_obj = TenantSettings.objects.get(tenant=tenant)
    except TenantSettings.DoesNotExist:
        settings_obj = TenantSettings.objects.create(tenant=tenant)
    
    # Handle POST request
    if request.method == 'POST':
        try:
            # Debug - log all POST data
            print("\n=== SETTINGS POST DATA ===")
            for key, value in request.POST.items():
                print(f"  {key}: {value}")
            print("============================\n")
            
            # Update tenant basic info
            tenant.company_name = request.POST.get('company_name', tenant.company_name)
            tenant.company_address = request.POST.get('company_address', tenant.company_address)
            tenant.company_phone = request.POST.get('company_phone', tenant.company_phone)
            tenant.company_email = request.POST.get('company_email', tenant.company_email)
            tenant.primary_color = request.POST.get('primary_color', tenant.primary_color)
            tenant.secondary_color = request.POST.get('secondary_color', tenant.secondary_color)
            tenant.accent_color = request.POST.get('accent_color', tenant.accent_color)
            
            # Handle file uploads
            if request.FILES.get('logo'):
                tenant.logo = request.FILES.get('logo')
                tenant.storage_used += request.FILES.get('logo').size
            if request.FILES.get('favicon'):
                tenant.favicon = request.FILES.get('favicon')
                tenant.storage_used += request.FILES.get('favicon').size
            
            tenant.save()
            
            # ===== UPDATE SETTINGS =====
            
            # Notification settings
            settings_obj.enable_notifications = request.POST.get('enable_notifications') == 'on'
            settings_obj.enable_email_notifications = request.POST.get('enable_email_notifications') == 'on'
            settings_obj.enable_sms_notifications = request.POST.get('enable_sms_notifications') == 'on'
            settings_obj.timezone = request.POST.get('timezone', settings_obj.timezone)
            settings_obj.currency = request.POST.get('currency', settings_obj.currency)
            settings_obj.date_format = request.POST.get('date_format', settings_obj.date_format)
            settings_obj.time_format = request.POST.get('time_format', settings_obj.time_format)
            
            # ===== TAX SETTINGS =====
            # Get tax_rate with proper handling
            tax_rate_raw = request.POST.get('tax_rate', '18')
            print(f"Tax rate raw value: '{tax_rate_raw}'")
            
            if tax_rate_raw == '' or tax_rate_raw is None:
                tax_rate_raw = '18'
            
            try:
                settings_obj.tax_rate = Decimal(str(tax_rate_raw))
                print(f"Tax rate set to: {settings_obj.tax_rate}")
            except (ValueError, TypeError) as e:
                print(f"Error parsing tax rate: {e}")
                settings_obj.tax_rate = Decimal('18')
            
            # Tax inclusive checkbox
            settings_obj.tax_inclusive = request.POST.get('tax_inclusive') == 'on'
            print(f"Tax inclusive: {settings_obj.tax_inclusive}")
            
            # ===== INVOICE SETTINGS =====
            settings_obj.invoice_prefix = request.POST.get('invoice_prefix', 'INV')
            settings_obj.invoice_footer = request.POST.get('invoice_footer', '')
            print(f"Invoice prefix: {settings_obj.invoice_prefix}")
            print(f"Invoice footer: {settings_obj.invoice_footer}")
            
            # ===== PAYMENT SETTINGS =====
            settings_obj.payment_terms = request.POST.get('payment_terms', 'Due on receipt')
            print(f"Payment terms: {settings_obj.payment_terms}")
            
            # Late fee percent
            late_fee_raw = request.POST.get('late_fee_percent', '0')
            print(f"Late fee raw value: '{late_fee_raw}'")
            
            if late_fee_raw == '' or late_fee_raw is None:
                late_fee_raw = '0'
            
            try:
                settings_obj.late_fee_percent = Decimal(str(late_fee_raw))
                print(f"Late fee set to: {settings_obj.late_fee_percent}")
            except (ValueError, TypeError) as e:
                print(f"Error parsing late fee: {e}")
                settings_obj.late_fee_percent = Decimal('0')
            
            # Save settings
            settings_obj.save()
            
            print("\n=== SETTINGS SAVED SUCCESSFULLY ===")
            print(f"Tax rate: {settings_obj.tax_rate}")
            print(f"Tax inclusive: {settings_obj.tax_inclusive}")
            print(f"Invoice prefix: {settings_obj.invoice_prefix}")
            print("====================================\n")
            
            messages.success(request, 'Settings updated successfully!')
            return redirect('accounts:settings')
            
        except Exception as e:
            print(f"ERROR in settings_view: {str(e)}")
            import traceback
            traceback.print_exc()
            messages.error(request, f'Error updating settings: {str(e)}')
            logger.error(f"Settings update error: {str(e)}")
            return redirect('accounts:settings')
    
    # GET request - show the form
    total_users = User.objects.filter(tenant=tenant).count()
    
    context = {
        'tenant': tenant,
        'settings': settings_obj,
        'total_users': total_users,
        'title': 'Settings - PharmaPro'
    }
    
    return render(request, 'accounts/settings.html', context)

def verify_email_view(request):
    """Verify user email"""
    token = request.GET.get('token')
    if not token:
        messages.error(request, 'Invalid verification token.')
        return redirect('accounts:login')
    
    try:
        user = User.objects.get(email_verification_token=token)
        if user.email_verified:
            messages.info(request, 'Your email is already verified.')
        else:
            user.email_verified = True
            user.is_active = True
            user.save()
            messages.success(request, 'Your email has been verified successfully! You can now login.')
    except User.DoesNotExist:
        messages.error(request, 'Invalid verification token.')
    
    return redirect('accounts:login')


def password_reset_view(request):
    """Password reset request view"""
    
    if request.method == 'POST':
        email = request.POST.get('email')

        if not email:
            messages.error(request, 'Please enter your email address.')
            return redirect('accounts:password_reset')

        try:
            user = User.objects.get(email=email)

            # Generate reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            domain = request.get_host()
            protocol = 'https' if request.is_secure() else 'http'

            reset_url = (
                f"{protocol}://{domain}"
                f"/accounts/password-reset-confirm/{uid}/{token}/"
            )

            context = {
                'user': user,
                'reset_url': reset_url,
                'site_name': 'PharmaPro',
                'domain': domain,
                'protocol': protocol,
            }

            html_message = render_to_string(
                'accounts/email/password_reset.html',
                context
            )

            plain_message = render_to_string(
                'accounts/email/password_reset.txt',
                context
            )

            send_mail(
                'Password Reset - PharmaPro',
                plain_message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=html_message,
                fail_silently=False
            )

            messages.success(
                request,
                'Password reset link has been sent. Please check your email.'
            )

            return redirect('accounts:password_reset_done')


        except User.DoesNotExist:

            # Security improvement:
            # Do not reveal whether email exists
            messages.success(
                request,
                'If an account exists with this email, a reset link has been sent.'
            )

            return redirect('accounts:password_reset')


    # GET request

    context = {
        'title': 'Password Reset - PharmaPro',
        'tenant': getattr(request.user, 'tenant', None)
    }

    return render(
        request,
        'accounts/password_reset.html',
        context
    )

def password_reset_confirm_view(request, uidb64, token):
    """Password reset confirm view"""
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    
    if user is not None and default_token_generator.check_token(user, token):
        if request.method == 'POST':
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')
            
            if not new_password or not confirm_password:
                messages.error(request, 'Please fill all fields.')
                return redirect('accounts:password_reset_confirm', uidb64=uidb64, token=token)
            
            if new_password != confirm_password:
                messages.error(request, 'Passwords do not match.')
                return redirect('accounts:password_reset_confirm', uidb64=uidb64, token=token)
            
            if len(new_password) < 8:
                messages.error(request, 'Password must be at least 8 characters long.')
                return redirect('accounts:password_reset_confirm', uidb64=uidb64, token=token)
            
            user.set_password(new_password)
            user.save()
            
            messages.success(request, 'Password has been reset successfully. You can now login.')
            return redirect('accounts:login')
        
        context = {
            'uidb64': uidb64,
            'token': token,
            'title': 'Reset Password - PharmaPro'
        }
        return render(request, 'accounts/password_reset_confirm.html', context)
    else:
        messages.error(request, 'Invalid or expired password reset link.')
        return redirect('accounts:password_reset')

# ============ NOTIFICATION VIEWS ============

@login_required
def notifications_view(request):
    """View all notifications"""
    user = request.user
    tenant = user.tenant
    
    # Get filter parameters
    notification_type = request.GET.get('type', '')
    category = request.GET.get('category', '')
    is_read = request.GET.get('is_read', '')
    
    # Base queryset
    notifications = Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    )
    
    # Apply filters
    if notification_type:
        notifications = notifications.filter(notification_type=notification_type)
    if category:
        notifications = notifications.filter(category=category)
    if is_read == 'read':
        notifications = notifications.filter(is_read=True)
    elif is_read == 'unread':
        notifications = notifications.filter(is_read=False)
    
    # Mark all as read if requested
    if request.GET.get('mark_all_read'):
        notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
        messages.success(request, 'All notifications marked as read.')
        return redirect('accounts:notifications')
    
    # Pagination
    paginator = Paginator(notifications, 20)
    page_number = request.GET.get('page', 1)
    notifications_page = paginator.get_page(page_number)
    
    # Get statistics
    total_count = Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).count()
    
    unread_count = Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        is_read=False,
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).count()
    
    # Get notification types for filter
    notification_types = Notification.NOTIFICATION_TYPES
    categories = Notification.NOTIFICATION_CATEGORIES
    
    context = {
        'notifications': notifications_page,
        'total_count': total_count,
        'unread_count': unread_count,
        'notification_types': notification_types,
        'categories': categories,
        'current_type': notification_type,
        'current_category': category,
        'current_status': is_read,
        'title': 'Notifications - PharmaPro'
    }
    return render(request, 'accounts/notifications.html', context)


@login_required
def notification_detail_view(request, notification_id):
    """View a single notification detail"""
    user = request.user
    tenant = user.tenant
    
    notification = get_object_or_404(
        Notification,
        models.Q(id=notification_id),
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True)
    )
    
    # Mark as read
    if not notification.is_read:
        notification.mark_as_read()
    
    context = {
        'notification': notification,
        'title': notification.title
    }
    return render(request, 'accounts/notification_detail.html', context)


@login_required
def notification_mark_read_view(request, notification_id):
    """Mark a single notification as read via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    user = request.user
    tenant = user.tenant
    
    try:
        notification = Notification.objects.get(
            models.Q(id=notification_id),
            models.Q(user=user) | models.Q(tenant=tenant, is_global=True)
        )
        notification.mark_as_read()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification marked as read'
        })
    except Notification.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Notification not found'
        }, status=404)


@login_required
def notification_mark_all_read_view(request):
    """Mark all notifications as read"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    user = request.user
    tenant = user.tenant
    
    Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        is_read=False,
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).update(is_read=True, read_at=timezone.now())
    
    return JsonResponse({
        'success': True,
        'message': 'All notifications marked as read'
    })


@login_required
def notification_delete_view(request, notification_id):
    """Delete a notification"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    user = request.user
    tenant = user.tenant
    
    try:
        notification = Notification.objects.get(
            models.Q(id=notification_id),
            models.Q(user=user) | models.Q(tenant=tenant, is_global=True)
        )
        notification.delete()
        
        return JsonResponse({
            'success': True,
            'message': 'Notification deleted'
        })
    except Notification.DoesNotExist:
        return JsonResponse({
            'success': False,
            'message': 'Notification not found'
        }, status=404)


# apps/accounts/views.py - Update get_notifications_api

@login_required
def get_notifications_api(request):
    """API endpoint to get notifications for the bell icon with sound support"""
    user = request.user
    tenant = user.tenant
    
    # Get previous count from session
    previous_count = request.session.get('notification_count', 0)
    
    # Get unread count
    unread_count = Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        is_read=False,
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).count()
    
    # Check if there are new notifications
    has_new_notifications = unread_count > previous_count
    
    # Update session with current count
    request.session['notification_count'] = unread_count
    
    # Get recent notifications
    recent = Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).order_by('-created_at')[:5]
    
    notifications_data = []
    for notif in recent:
        notifications_data.append({
            'id': str(notif.id),
            'title': notif.title,
            'message': notif.message,
            'notification_type': notif.notification_type,
            'is_read': notif.is_read,
            'created_at': notif.created_at.isoformat(),
            'link': notif.link,
            'link_text': notif.link_text,
            'icon': notif.icon or get_notification_icon(notif.notification_type)
        })
    
    return JsonResponse({
        'success': True,
        'unread_count': unread_count,
        'notifications': notifications_data,
        'has_new_notifications': has_new_notifications,
        'previous_count': previous_count
    })


def get_notification_icon(notification_type):
    """Get icon for notification type"""
    icons = {
        'info': 'fa-info-circle',
        'success': 'fa-check-circle',
        'warning': 'fa-exclamation-triangle',
        'error': 'fa-times-circle',
        'alert': 'fa-bell',
    }
    return icons.get(notification_type, 'fa-bell')


@login_required
def mark_notifications_read(request):
    """Mark all notifications as read"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    user = request.user
    tenant = user.tenant
    
    Notification.objects.filter(
        models.Q(user=user) | models.Q(tenant=tenant, is_global=True),
        is_read=False,
        expires_at__isnull=True
    ).exclude(
        expires_at__lte=timezone.now()
    ).update(is_read=True, read_at=timezone.now())
    
    return JsonResponse({'success': True, 'message': 'All notifications marked as read'})

def landing_view(request):
    """Landing page view"""
    return render(request, 'accounts/landing.html', {
        'title': 'Welcome - PharmaPro'
    })


def dashboard_view(request):
    """Dashboard view for authenticated users - redirects based on role"""
    if request.user.is_authenticated:
        # Get redirect URL based on user role
        redirect_url = get_role_redirect_url(request, request.user)
        return redirect(redirect_url)
    else:
        return redirect('accounts:login')

# Helper functions
def send_welcome_email(user, tenant):
    """Send welcome email to new user"""
    subject = f'Welcome to {tenant.company_name} - PharmaPro'
    context = {
        'user': user,
        'tenant': tenant,
        'login_url': f'/login/?tenant={tenant.slug}'
    }
    html_message = render_to_string('accounts/email/welcome.html', context)
    plain_message = render_to_string('accounts/email/welcome.txt', context)
    
    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False
    )


# apps/accounts/views.py - Updated send_user_welcome_email

def send_user_welcome_email(user, password):
    """Send welcome email to new user created by admin with login credentials"""
    import logging
    import os
    logger = logging.getLogger(__name__)
    
    try:
        tenant = user.tenant
        subject = f'Welcome to {tenant.company_name} - PharmaPro'
        
        # Build context
        context = {
            'user': user,
            'tenant': tenant,
            'password': password,
            'login_url': f'/login/?tenant={tenant.slug}',
            'profile_url': '/accounts/profile/'
        }
        
        # Check if templates exist
        html_template_path = 'accounts/email/user_welcome.html'
        txt_template_path = 'accounts/email/user_welcome.txt'
        
        # Try to render HTML template
        try:
            html_message = render_to_string(html_template_path, context)
        except Exception as e:
            logger.error(f"Failed to render HTML template: {e}")
            # Fallback to simple HTML
            html_message = f"""
            <h1>Welcome to {tenant.company_name}</h1>
            <p>Hello {user.get_full_name()},</p>
            <p>Your account has been created.</p>
            <p><strong>Email:</strong> {user.email}</p>
            <p><strong>Password:</strong> {password}</p>
            <p><a href="http://localhost:8000{context['login_url']}">Login Now</a></p>
            """
        
        # Try to render plain text template
        try:
            plain_message = render_to_string(txt_template_path, context)
        except Exception as e:
            logger.error(f"Failed to render text template: {e}")
            # Fallback to simple text
            plain_message = f"""
        Welcome to {tenant.company_name}

        Hello {user.get_full_name()},

        Your account has been created.

        Your Login Credentials:
        Email: {user.email}
        Password: {password}

        Login URL: http://localhost:8000{context['login_url']}
        """
        
        # Send email
        logger.info(f"Sending welcome email to {user.email}")
        send_mail(
            subject,
            plain_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Welcome email sent successfully to {user.email}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending welcome email to {user.email}: {str(e)}")
        print(f"Error sending email: {e}")
        return False
    



def send_password_changed_email(user, new_password):
    """Send password changed notification email"""
    tenant = user.tenant
    subject = f'Your password has been changed - {tenant.company_name}'
    context = {
        'user': user,
        'tenant': tenant,
        'password': new_password,
        'login_url': f'/login/?tenant={tenant.slug}'
    }
    html_message = render_to_string('accounts/email/password_changed.html', context)
    plain_message = render_to_string('accounts/email/password_changed.txt', context)
    
    send_mail(
        subject,
        plain_message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False
    )





def render_full_dashboard(request, tenant):
    """Render the full dashboard for admins"""
    from inventory.models import Product
    from sales.models import Sale
    from accounts.models import User
    from django.db.models import Sum, F
    from django.db.models.functions import TruncMonth
    from django.utils import timezone
    
    total_products = Product.objects.filter(tenant=tenant).count()
    total_sales = Sale.objects.filter(tenant=tenant).count()
    total_users = User.objects.filter(tenant=tenant).count()
    online_users = User.objects.filter(tenant=tenant, is_online=True).count()
    
    # Get recent sales
    recent_sales = Sale.objects.filter(tenant=tenant).order_by('-sale_date')[:10]
    
    # Get low stock products
    low_stock = Product.objects.filter(
        tenant=tenant,
        quantity__lte=F('reorder_point'),
        is_active=True
    )[:10]
    
    # Sales data for chart
    sales_data = Sale.objects.filter(
        tenant=tenant,
        sale_date__date=timezone.now().date()
    ).aggregate(
        total=Sum('total_amount')
    )
    
    # Get monthly sales for chart
    monthly_sales = Sale.objects.filter(
        tenant=tenant
    ).annotate(
        month=TruncMonth('sale_date')
    ).values('month').annotate(
        total=Sum('total_amount')
    ).order_by('month')
    
    context = {
        'tenant': tenant,
        'total_products': total_products,
        'total_sales': total_sales,
        'total_users': total_users,
        'online_users': online_users,
        'recent_sales': recent_sales,
        'low_stock': low_stock,
        'today_sales': sales_data['total'] or 0,
        'monthly_sales': list(monthly_sales),
        'title': f'{tenant.name} Dashboard - PharmaPro'
    }
    return render(request, 'tenants/dashboard.html', context)



# apps/accounts/views.py
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@login_required
@csrf_exempt  # Add this decorator to bypass CSRF for this AJAX endpoint
@require_http_methods(["POST"])
def update_user_online_status(request):
    """Update user online status via AJAX"""
    try:
        user = request.user
        is_online = request.POST.get('is_online') == 'true'
        user.is_online = is_online
        if is_online:
            user.last_activity = timezone.now()
        user.save(update_fields=['is_online', 'last_activity'])
        return JsonResponse({'success': True, 'is_online': user.is_online})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@login_required
def get_online_users(request):
    """Get online users for the current tenant via AJAX"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return JsonResponse({
            'success': False,
            'error': 'You do not have permission to view online users.'
        }, status=403)
    
    try:
        tenant = request.user.tenant
        online_users = User.objects.filter(tenant=tenant, is_online=True).values(
            'id', 'first_name', 'last_name', 'email', 'role', 'last_activity'
        )
        return JsonResponse({
            'success': True,
            'online_users': list(online_users),
            'count': online_users.count()
        })
    except Exception as e:
        return JsonResponse({
            'success': False, 
            'error': str(e)
        }, status=400) 

# apps/accounts/views.py - Add these new views

# apps/accounts/views.py - Updated online_users_view

from django.core.cache import cache

@login_required
def online_users_view(request):
    """View to show all online users"""
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    tenant = request.user.tenant
    
    # Try to get from cache
    cache_key = f'online_users_{tenant.id}'
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return render(request, 'accounts/online_users.html', cached_data)
    
    online_users = User.objects.filter(tenant=tenant, is_online=True).order_by('-last_activity')
    total_users = User.objects.filter(tenant=tenant).count()
    online_count = online_users.count()
    
    # Get user activity for online users
    for user in online_users:
        last_activity = UserActivity.objects.filter(user=user).order_by('-timestamp').first()
        user.last_action = last_activity.action if last_activity else 'No activity'
        user.last_action_time = last_activity.timestamp if last_activity else user.last_activity
    
    context = {
        'online_users': online_users,
        'total_users': total_users,
        'online_count': online_count,
        'title': 'Online Users - PharmaPro'
    }
    
    # Cache for 15 seconds
    cache.set(cache_key, context, 15)
    
    return render(request, 'accounts/online_users.html', context)

# apps/accounts/views.py - Update user_detail_view

# apps/accounts/views.py - Update user_detail_view

@login_required
def user_detail_view(request, user_id):
    """View user details"""
    # Check if user has permission
    if not user_can_manage_users(request.user):
        return render(request, 'accounts/access_denied.html', {'title': 'Access Denied'})
    
    # Handle UUID conversion
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = User.objects.get(id=user_id, tenant=request.user.tenant)
    except (ValueError, TypeError, User.DoesNotExist):
        messages.error(request, 'User not found or you do not have permission to view this user.')
        return redirect('accounts:user_list')
    
    # Get user activity
    activities = UserActivity.objects.filter(user=user).order_by('-timestamp')[:20]
    
    # Get user statistics
    from django.db.models import Count
    from django.utils import timezone
    from datetime import timedelta
    
    # Activity stats
    last_7_days = timezone.now() - timedelta(days=7)
    recent_activities = UserActivity.objects.filter(
        user=user,
        timestamp__gte=last_7_days
    ).count()
    
    # Online status history (simplified)
    is_online = user.is_online
    last_seen = user.last_activity
    
    context = {
        'viewed_user': user,  # Use viewed_user instead of user to avoid confusion
        'activities': activities,
        'recent_activities': recent_activities,
        'is_online': is_online,
        'last_seen': last_seen,
        'title': f'User Details - {user.get_full_name()}'
    }
    return render(request, 'accounts/user_detail.html', context)




def password_reset_done_view(request):
    """Password reset done view"""
    context = {
        'title': 'Password Reset Sent - PharmaPro'
    }
    return render(request, 'accounts/password_reset_done.html', context)



# apps/accounts/views.py - Add this new view

@staff_member_required
def superuser_user_list_view(request):
    """Superuser view to list all users across all tenants"""
    users = User.objects.all().select_related('tenant').order_by('-date_joined')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(tenant__company_name__icontains=search_query) |
            Q(tenant__name__icontains=search_query)
        )
    
    # Filter by role
    role_filter = request.GET.get('role', '')
    if role_filter:
        users = users.filter(role=role_filter)
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        if status_filter == 'online':
            users = users.filter(is_online=True)
        elif status_filter == 'offline':
            users = users.filter(is_online=False)
        elif status_filter == 'active':
            users = users.filter(is_active=True)
        elif status_filter == 'inactive':
            users = users.filter(is_active=False)
    
    # Filter by tenant
    tenant_filter = request.GET.get('tenant', '')
    if tenant_filter:
        users = users.filter(tenant_id=tenant_filter)
    
    # Get statistics
    total_users = users.count()
    online_users = users.filter(is_online=True).count()
    active_users = users.filter(is_active=True).count()
    super_admins = users.filter(is_superuser=True).count()
    admins = users.filter(role='admin').count()
    
    # Pagination
    paginator = Paginator(users, 20)
    page_number = request.GET.get('page', 1)
    users_page = paginator.get_page(page_number)
    
    # Get all tenants for filter dropdown
    tenants = Tenant.objects.all().order_by('company_name')
    
    context = {
        'users': users_page,
        'total_users': total_users,
        'online_users': online_users,
        'active_users': active_users,
        'super_admins': super_admins,
        'admins': admins,
        'search_query': search_query,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'tenant_filter': tenant_filter,
        'tenants': tenants,
        'roles': User.ROLE_CHOICES,
        'title': 'All Users - PharmaPro Admin'
    }
    return render(request, 'accounts/superuser_users.html', context)



# apps/accounts/views.py - Update superuser_user_detail_view

@staff_member_required
def superuser_user_detail_view(request, user_id):
    """Superuser view to see any user's details"""
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        viewed_user = User.objects.get(id=user_id)  # Change variable name
    except (ValueError, TypeError, User.DoesNotExist):
        messages.error(request, 'User not found.')
        return redirect('accounts:superuser_users')
    
    # Get user activity
    activities = UserActivity.objects.filter(user=viewed_user).order_by('-timestamp')[:30]
    
    # Get user statistics
    from django.db.models import Count
    from django.utils import timezone
    from datetime import timedelta
    
    last_7_days = timezone.now() - timedelta(days=7)
    recent_activities = UserActivity.objects.filter(
        user=viewed_user,
        timestamp__gte=last_7_days
    ).count()
    
    # Get tenant details
    tenant = viewed_user.tenant
    
    context = {
        'viewed_user': viewed_user,  # Only pass viewed_user, NOT 'user'
        'tenant': tenant,
        'activities': activities,
        'recent_activities': recent_activities,
        'is_online': viewed_user.is_online,
        'last_seen': viewed_user.last_activity,
        'title': f'User Details - {viewed_user.get_full_name()}'
    }
    return render(request, 'accounts/superuser_user_detail.html', context)



@staff_member_required
def superuser_user_toggle_active_view(request, user_id):
    """Superuser view to toggle user active status"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = User.objects.get(id=user_id)
    except (ValueError, TypeError, User.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'User not found.'}, status=404)
    
    # Don't allow deactivating self
    if user.id == request.user.id:
        return JsonResponse({
            'success': False,
            'error': 'You cannot change your own status.'
        }, status=400)
    
    # Don't allow deactivating other super admins
    if user.is_superuser and not request.user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': 'You cannot change the status of a super admin.'
        }, status=403)
    
    try:
        user.is_active = not user.is_active
        if not user.is_active:
            user.is_online = False
        user.save(update_fields=['is_active', 'is_online'])
        
        return JsonResponse({
            'success': True,
            'message': f"User {'activated' if user.is_active else 'deactivated'} successfully",
            'is_active': user.is_active,
            'is_online': user.is_online
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@staff_member_required
def superuser_user_make_admin_view(request, user_id):
    """Superuser view to make a user an admin"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = User.objects.get(id=user_id)
    except (ValueError, TypeError, User.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'User not found.'}, status=404)
    
    # Don't allow changing self
    if user.id == request.user.id:
        return JsonResponse({
            'success': False,
            'error': 'You cannot change your own role.'
        }, status=400)
    
    try:
        user.role = 'admin'
        user.is_superuser = False
        user.save(update_fields=['role', 'is_superuser'])
        
        return JsonResponse({
            'success': True,
            'message': f"{user.get_full_name()} is now an admin."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@staff_member_required
def superuser_user_make_superadmin_view(request, user_id):
    """Superuser view to make a user a super admin"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = User.objects.get(id=user_id)
    except (ValueError, TypeError, User.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'User not found.'}, status=404)
    
    # Don't allow changing self
    if user.id == request.user.id:
        return JsonResponse({
            'success': False,
            'error': 'You cannot change your own role.'
        }, status=400)
    
    try:
        user.is_superuser = True
        user.role = 'admin'  # Keep role as admin but mark as superuser
        user.save(update_fields=['is_superuser', 'role'])
        
        return JsonResponse({
            'success': True,
            'message': f"{user.get_full_name()} is now a super admin."
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@staff_member_required
def superuser_user_delete_view(request, user_id):
    """Superuser view to delete any user"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        import uuid
        if isinstance(user_id, str):
            user_id = uuid.UUID(user_id)
        user = User.objects.get(id=user_id)
    except (ValueError, TypeError, User.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'User not found.'}, status=404)
    
    # Don't allow deleting self
    if user.id == request.user.id:
        return JsonResponse({
            'success': False,
            'error': 'You cannot delete your own account.'
        }, status=400)
    
    # Don't allow deleting other super admins
    if user.is_superuser:
        return JsonResponse({
            'success': False,
            'error': 'You cannot delete another super admin.'
        }, status=403)
    
    try:
        user_name = user.get_full_name()
        user.delete()
        
        return JsonResponse({
            'success': True,
            'message': f"User {user_name} deleted successfully.",
            'redirect_url': reverse('accounts:superuser_users')
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    


# apps/accounts/views.py - Add these view functions

# ============ SUPERADMIN SUBSCRIPTION VIEWS ============

@staff_member_required
def superuser_subscription_view(request):
    """Superuser view to manage all subscriptions"""
    from tenants.models import Tenant
    from django.db.models import Sum, Q
    
    subscriptions = Tenant.objects.all().order_by('-created_at')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        subscriptions = subscriptions.filter(
            Q(company_name__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(slug__icontains=search_query) |
            Q(company_email__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        subscriptions = subscriptions.filter(subscription_status=status_filter)
    
    # Filter by plan
    plan_filter = request.GET.get('plan', '')
    if plan_filter:
        subscriptions = subscriptions.filter(plan=plan_filter)
    
    # Get statistics
    total_subscriptions = subscriptions.count()
    active_subscriptions = subscriptions.filter(subscription_status='active').count()
    expiring_soon = subscriptions.filter(
        subscription_end_date__lte=timezone.now() + timedelta(days=3),
        subscription_end_date__gte=timezone.now()
    ).count()
    
    # Get total revenue (from subscription logs)
    total_revenue = SubscriptionLog.objects.filter(
        action='payment_succeeded'
    ).aggregate(
        total=Sum('details__amount')
    )['total'] or 0
    
    # Get user count for each tenant and set display dates
    for tenant in subscriptions:
        tenant.user_count = User.objects.filter(tenant=tenant).count()
        
        # Set display dates based on subscription status
        if tenant.subscription_status == 'trial':
            # For trial tenants, use trial dates
            tenant.display_start_date = tenant.trial_start_date
            tenant.display_end_date = tenant.trial_end_date
        else:
            # For other statuses, use subscription dates
            tenant.display_start_date = tenant.subscription_start_date
            tenant.display_end_date = tenant.subscription_end_date
    
    # Pagination
    paginator = Paginator(subscriptions, 20)
    page_number = request.GET.get('page', 1)
    subscriptions_page = paginator.get_page(page_number)
    
    context = {
        'subscriptions': subscriptions_page,
        'total_subscriptions': total_subscriptions,
        'active_subscriptions': active_subscriptions,
        'expiring_soon': expiring_soon,
        'total_revenue': total_revenue,
        'search_query': search_query,
        'status_filter': status_filter,
        'plan_filter': plan_filter,
        'title': 'Subscription Management - PharmaPro'
    }
    return render(request, 'accounts/superuser_subscription.html', context)

@staff_member_required
def superuser_subscription_renew(request, tenant_id):
    """Superuser view to renew a subscription"""
    from tenants.models import Tenant
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    try:
        # Extend subscription by 30 days
        if tenant.subscription_end_date:
            new_end_date = max(tenant.subscription_end_date, timezone.now()) + timedelta(days=30)
        else:
            new_end_date = timezone.now() + timedelta(days=30)
        
        tenant.subscription_end_date = new_end_date
        tenant.subscription_status = 'active'
        tenant.subscription_start_date = timezone.now()
        tenant.save()
        
        # Log the renewal
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='renewed_by_admin',
            details={
                'renewed_by': request.user.username,
                'new_end_date': new_end_date.isoformat()
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Subscription renewed for {tenant.company_name}'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


@staff_member_required
def superuser_subscription_cancel(request, tenant_id):
    """Superuser view to cancel a subscription"""
    from tenants.models import Tenant
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    try:
        tenant.subscription_status = 'cancelled'
        tenant.subscription_end_date = timezone.now()
        tenant.save()
        
        # Cancel Stripe subscription if exists
        if tenant.stripe_subscription_id:
            try:
                stripe.Subscription.delete(tenant.stripe_subscription_id)
            except Exception as e:
                logger.error(f"Error cancelling Stripe subscription: {str(e)}")
        
        # Log the cancellation
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='cancelled_by_admin',
            details={
                'cancelled_by': request.user.username,
                'cancelled_at': timezone.now().isoformat()
            }
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Subscription cancelled for {tenant.company_name}'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)


# ============ SUPERADMIN SETTINGS VIEWS ============

@staff_member_required
def superuser_settings_view(request):
    """Superuser view for system settings"""
    from .models import SystemSettings
    
    # Get or create system settings
    try:
        settings = SystemSettings.objects.first()
        if not settings:
            settings = SystemSettings.objects.create()
    except:
        settings = SystemSettings.objects.create()
    
    if request.method == 'POST':
        # Update general settings
        settings.site_name = request.POST.get('site_name', settings.site_name)
        settings.site_url = request.POST.get('site_url', settings.site_url)
        settings.admin_email = request.POST.get('admin_email', settings.admin_email)
        settings.support_email = request.POST.get('support_email', settings.support_email)
        settings.maintenance_mode = request.POST.get('maintenance_mode') == 'on'
        settings.maintenance_message = request.POST.get('maintenance_message', settings.maintenance_message)
        
        # Update branding
        settings.primary_color = request.POST.get('primary_color', settings.primary_color)
        settings.secondary_color = request.POST.get('secondary_color', settings.secondary_color)
        settings.accent_color = request.POST.get('accent_color', settings.accent_color)
        
        # Handle file uploads
        if request.FILES.get('site_logo'):
            settings.site_logo = request.FILES.get('site_logo')
        if request.FILES.get('site_favicon'):
            settings.site_favicon = request.FILES.get('site_favicon')
        
        # Update security settings
        settings.allow_registration = request.POST.get('allow_registration') == 'on'
        settings.require_verification = request.POST.get('require_verification') == 'on'
        settings.session_timeout = request.POST.get('session_timeout', settings.session_timeout)
        settings.force_ssl = request.POST.get('force_ssl') == 'on'
        
        # Update email settings
        settings.smtp_host = request.POST.get('smtp_host', settings.smtp_host)
        settings.smtp_port = request.POST.get('smtp_port', settings.smtp_port)
        settings.smtp_username = request.POST.get('smtp_username', settings.smtp_username)
        if request.POST.get('smtp_password'):
            settings.smtp_password = request.POST.get('smtp_password')
        settings.use_tls = request.POST.get('use_tls') == 'on'
        
        # Update Stripe settings
        settings.stripe_publishable_key = request.POST.get('stripe_publishable_key', settings.stripe_publishable_key)
        if request.POST.get('stripe_secret_key'):
            settings.stripe_secret_key = request.POST.get('stripe_secret_key')
        settings.stripe_webhook_secret = request.POST.get('stripe_webhook_secret', settings.stripe_webhook_secret)
        settings.stripe_test_mode = request.POST.get('stripe_test_mode') == 'on'
        
        settings.save()
        
        messages.success(request, 'System settings updated successfully!')
        return redirect('accounts:superuser_settings')
    
    context = {
        'settings': settings,
        'title': 'System Settings - PharmaPro'
    }
    return render(request, 'accounts/superuser_settings.html', context)


@staff_member_required
def superuser_settings_reset(request):
    """Reset system settings to defaults"""
    from .models import SystemSettings
    
    if request.method != 'POST':
        return redirect('accounts:superuser_settings')
    
    try:
        settings = SystemSettings.objects.first()
        if settings:
            settings.delete()
        messages.success(request, 'Settings have been reset to defaults.')
    except Exception as e:
        messages.error(request, f'Error resetting settings: {str(e)}')
    
    return redirect('accounts:superuser_settings')


# ============ SUPERADMIN LOGS VIEWS ============
@staff_member_required
def superuser_logs_view(request):
    """Superuser view for system logs"""
    from .models import UserActivity
    from tenants.models import Tenant
    
    logs = UserActivity.objects.all().order_by('-timestamp')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        logs = logs.filter(
            Q(action__icontains=search_query) |
            Q(model_name__icontains=search_query) |
            Q(object_id__icontains=search_query) |
            Q(ip_address__icontains=search_query)
        )
    
    # Filter by action
    action_filter = request.GET.get('action', '')
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    
    # Filter by user
    user_filter = request.GET.get('user', '')
    if user_filter:
        logs = logs.filter(user_id=user_filter)
    
    # Filter by tenant - FIXED: Removed is_active filter
    tenant_filter = request.GET.get('tenant', '')
    if tenant_filter:
        logs = logs.filter(user__tenant_id=tenant_filter)
    
    # Filter by date
    date_filter = request.GET.get('date', '')
    if date_filter:
        now = timezone.now()
        if date_filter == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            logs = logs.filter(timestamp__gte=start_date)
        elif date_filter == 'week':
            start_date = now - timedelta(days=7)
            logs = logs.filter(timestamp__gte=start_date)
        elif date_filter == 'month':
            start_date = now - timedelta(days=30)
            logs = logs.filter(timestamp__gte=start_date)
    
    # Get statistics
    total_logs = UserActivity.objects.count()
    today_logs = UserActivity.objects.filter(
        timestamp__gte=timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    ).count()
    week_logs = UserActivity.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=7)
    ).count()
    month_logs = UserActivity.objects.filter(
        timestamp__gte=timezone.now() - timedelta(days=30)
    ).count()
    
    # Get all users and tenants for filters - FIXED: Removed is_active filter
    users = User.objects.filter(is_active=True).order_by('first_name')
    # Get all tenants that have at least one user or are active
    tenants = Tenant.objects.all().order_by('company_name')
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page', 1)
    logs_page = paginator.get_page(page_number)
    
    context = {
        'logs': logs_page,
        'total_logs': total_logs,
        'today_logs': today_logs,
        'week_logs': week_logs,
        'month_logs': month_logs,
        'search_query': search_query,
        'action_filter': action_filter,
        'user_filter': user_filter,
        'tenant_filter': tenant_filter,
        'date_filter': date_filter,
        'users': users,
        'tenants': tenants,
        'title': 'System Logs - PharmaPro'
    }
    return render(request, 'accounts/superuser_logs.html', context)


@staff_member_required
def superuser_clear_logs(request):
    """Clear all system logs"""
    from .models import UserActivity
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)
    
    try:
        count = UserActivity.objects.count()
        UserActivity.objects.all().delete()
        
        # Log this action
        UserActivity.objects.create(
            user=request.user,
            action='Cleared all logs',
            model_name='UserActivity',
            object_id='all',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT'),
            details={'count': count}
        )
        
        return JsonResponse({
            'success': True,
            'message': f'Successfully cleared {count} log entries'
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=400)
    


@staff_member_required
def superuser_user_create_view(request):
    """Superuser view to create a user for any tenant"""
    from tenants.utils import check_plan_limit, get_plan_limit, get_current_usage
    
    # Get all tenants for the dropdown
    tenants = Tenant.objects.all().order_by('company_name')
    
    if request.method == 'POST':
        try:
            tenant_id = request.POST.get('tenant_id')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            last_name = request.POST.get('last_name')
            role = request.POST.get('role', 'staff')
            password = request.POST.get('password')
            phone = request.POST.get('phone', '')
            is_active = request.POST.get('is_active') == 'on'
            is_superuser = request.POST.get('is_superuser') == 'on'
            
            # Validate
            if not all([tenant_id, email, first_name, last_name]):
                messages.error(request, 'Please fill all required fields.')
                return redirect('accounts:superuser_user_create')
            
            # Get the tenant
            try:
                import uuid
                tenant = Tenant.objects.get(id=uuid.UUID(tenant_id))
            except (ValueError, TypeError, Tenant.DoesNotExist):
                messages.error(request, 'Invalid organization selected.')
                return redirect('accounts:superuser_user_create')
            
            # Check if email already exists
            if User.objects.filter(email=email).exists():
                messages.error(request, 'A user with this email already exists.')
                return redirect('accounts:superuser_user_create')
            
            # Check if tenant has reached user limit (skip for superadmin users)
            if not is_superuser and not check_plan_limit(tenant, 'max_users'):
                current_users = get_current_usage(tenant, 'max_users')
                max_users = get_plan_limit(tenant, 'max_users')
                messages.error(
                    request, 
                    f'User limit reached for {tenant.company_name}! '
                    f'You have {current_users} users and the plan allows only {max_users} users.'
                )
                return redirect('accounts:superuser_user_create')
            
            # Generate default password if not provided
            if not password:
                org_name = tenant.company_name or tenant.name
                org_name_clean = ''.join(e for e in org_name if e.isalnum()).lower()
                current_year = timezone.now().year
                password = f"{org_name_clean}@{current_year}"
            
            # Create user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                role=role if not is_superuser else 'admin',
                phone=phone,
                tenant=tenant,
                can_view=True,
                email_verified=True,
                is_active=is_active,
                is_superuser=is_superuser
            )
            
            # Set permissions
            user.can_create = request.POST.get('can_create') == 'on'
            user.can_edit = request.POST.get('can_edit') == 'on'
            user.can_delete = request.POST.get('can_delete') == 'on'
            user.can_view = True
            user.save()
            
            # Send welcome email with login credentials
            send_user_welcome_email(user, password)
            
            messages.success(
                request, 
                f'User {user.get_full_name()} created successfully! Password: {password}'
            )
            return redirect('accounts:superuser_users')
            
        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
            return redirect('accounts:superuser_user_create')
    
    # GET request - show form
    context = {
        'tenants': tenants,
        'roles': User.ROLE_CHOICES,
        'title': 'Create User - Super Admin'
    }
    return render(request, 'accounts/superuser_user_create.html', context)