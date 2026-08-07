# apps/tenants/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q, F
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .models import Tenant, TenantSettings, SubscriptionLog
from accounts.models import User
from inventory.models import Product, StockMovement
from sales.models import Sale
import stripe
import json
import logging

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


@login_required
def dashboard_view(request):
    """Main dashboard for tenant"""
    tenant = request.user.tenant
    
    # Get statistics
    total_products = Product.objects.filter(tenant=tenant).count()
    total_sales = Sale.objects.filter(tenant=tenant).count()
    total_users = User.objects.filter(tenant=tenant).count()
    
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
    from django.db.models.functions import TruncMonth
    monthly_sales = Sale.objects.filter(
        tenant=tenant
    ).annotate(
        month=TruncMonth('sale_date')
    ).values('month').annotate(
        total=Sum('total_amount')
    ).order_by('month')
    
    context = {
        'total_products': total_products,
        'total_sales': total_sales,
        'total_users': total_users,
        'recent_sales': recent_sales,
        'low_stock': low_stock,
        'today_sales': sales_data['total'] or 0,
        'monthly_sales': list(monthly_sales),
        'title': 'Dashboard - PharmaPro'
    }
    return render(request, 'tenants/dashboard.html', context)


@login_required
def subscription_view(request):
    """Subscription management page"""
    tenant = request.user.tenant

     # Clear expiry session flags
    if 'subscription_expired' in request.session:
        del request.session['subscription_expired']
    if 'subscription_expiring_soon' in request.session:
        del request.session['subscription_expiring_soon']
    if 'subscription_warning_shown' in request.session:
        del request.session['subscription_warning_shown']
    if 'subscription_days_left' in request.session:
        del request.session['subscription_days_left']
    
    # Check if expired
    is_expired = tenant.is_expired()
    days_left = tenant.get_days_until_expiry()
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'renew':
            return handle_subscription_renewal(request, tenant)
        elif action == 'cancel':
            return handle_subscription_cancellation(request, tenant)
        elif action == 'change_plan':
            return handle_plan_change(request, tenant)
    
    # Get subscription details
    subscription_info = None
    upcoming_invoice = None
    payment_methods = []
    
    if tenant.stripe_subscription_id:
        try:
            subscription_info = stripe.Subscription.retrieve(
                tenant.stripe_subscription_id,
                expand=['latest_invoice', 'default_payment_method']
            )
            
            # Get upcoming invoice
            if tenant.stripe_customer_id:
                upcoming_invoice = stripe.Invoice.upcoming(
                    customer=tenant.stripe_customer_id
                )
                
            # Get payment methods
            if tenant.stripe_customer_id:
                payment_methods = stripe.PaymentMethod.list(
                    customer=tenant.stripe_customer_id,
                    type='card'
                )
                
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error: {str(e)}")
            messages.warning(request, f"Could not retrieve subscription details: {str(e)}")
    
    context = {
        'tenant': tenant,
        'subscription_info': subscription_info,
        'upcoming_invoice': upcoming_invoice,
        'payment_methods': payment_methods,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'plans': get_plan_details(),
        'is_expired': is_expired,
        'days_left': days_left,
        'title': 'Subscription - PharmaPro'
    }
    return render(request, 'tenants/subscription.html', context)


@login_required
def subscription_renew_view(request):
    """Handle subscription renewal"""
    tenant = request.user.tenant
    
    if request.method != 'POST':
        return redirect('tenants:subscription')
    
    return handle_subscription_renewal(request, tenant)


@login_required
def subscription_cancel_view(request):
    """Handle subscription cancellation"""
    tenant = request.user.tenant
    
    if request.method != 'POST':
        return redirect('tenants:subscription')
    
    return handle_subscription_cancellation(request, tenant)


@login_required
def subscription_change_plan_view(request):
    """Handle plan change"""
    tenant = request.user.tenant
    
    if request.method != 'POST':
        return redirect('tenants:subscription')
    
    return handle_plan_change(request, tenant)


def handle_subscription_renewal(request, tenant):
    """Process subscription renewal"""
    try:
        # Get payment method
        payment_method_id = request.POST.get('payment_method_id')
        if not payment_method_id:
            messages.error(request, 'Please provide payment details.')
            return redirect('tenants:subscription')
        
        # Create or get Stripe customer
        if not tenant.stripe_customer_id:
            customer = stripe.Customer.create(
                email=tenant.company_email or request.user.email,
                name=tenant.company_name or tenant.name,
                metadata={'tenant_id': str(tenant.id)}
            )
            tenant.stripe_customer_id = customer.id
            tenant.save()
        else:
            customer = stripe.Customer.retrieve(tenant.stripe_customer_id)
        
        # Attach payment method
        try:
            stripe.PaymentMethod.attach(
                payment_method_id,
                customer=tenant.stripe_customer_id
            )
        except stripe.error.InvalidRequestError:
            # Payment method might already be attached
            pass
        
        # Set as default payment method
        stripe.Customer.modify(
            tenant.stripe_customer_id,
            invoice_settings={
                'default_payment_method': payment_method_id
            }
        )
        
        # Create or update subscription
        price_id = get_price_id_for_plan(tenant.plan)
        
        if tenant.stripe_subscription_id:
            # Update existing subscription
            subscription = stripe.Subscription.modify(
                tenant.stripe_subscription_id,
                items=[{'price': price_id}],
                proration_behavior='create_prorations'
            )
        else:
            # Create new subscription
            subscription = stripe.Subscription.create(
                customer=tenant.stripe_customer_id,
                items=[{'price': price_id}],
                trial_period_days=0,
                metadata={'tenant_id': str(tenant.id)},
                payment_behavior='default_incomplete',
                expand=['latest_invoice.payment_intent']
            )
        
        # Update tenant
        tenant.stripe_subscription_id = subscription.id
        tenant.subscription_status = subscription.status
        tenant.subscription_start_date = timezone.now()
        
        if subscription.status in ['active', 'trialing']:
            tenant.subscription_end_date = timezone.now() + timezone.timedelta(days=30)
        
        tenant.save()
        
        # Log subscription
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='renewed',
            details={
                'subscription_id': subscription.id,
                'status': subscription.status,
                'plan': tenant.plan
            }
        )
        
        messages.success(request, 'Subscription renewed successfully!')
        
    except stripe.error.CardError as e:
        messages.error(request, f'Payment failed: {e.error.message}')
        logger.error(f"Stripe CardError: {str(e)}")
    except stripe.error.StripeError as e:
        messages.error(request, f'Payment error: {str(e)}')
        logger.error(f"Stripe error: {str(e)}")
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
        logger.error(f"Subscription renewal error: {str(e)}")
    
    return redirect('tenants:subscription')


def handle_subscription_cancellation(request, tenant):
    """Process subscription cancellation"""
    try:
        if not tenant.stripe_subscription_id:
            messages.error(request, 'No active subscription found.')
            return redirect('tenants:subscription')
        
        # Cancel at period end
        subscription = stripe.Subscription.modify(
            tenant.stripe_subscription_id,
            cancel_at_period_end=True
        )
        
        tenant.subscription_status = 'cancelling'
        tenant.save()
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='cancelled',
            details={
                'subscription_id': tenant.stripe_subscription_id,
                'cancel_at_period_end': True
            }
        )
        
        messages.success(request, 'Subscription will be cancelled at the end of the billing period.')
        
    except stripe.error.StripeError as e:
        messages.error(request, f'Error cancelling subscription: {str(e)}')
        logger.error(f"Stripe error: {str(e)}")
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
        logger.error(f"Cancellation error: {str(e)}")
    
    return redirect('tenants:subscription')


def handle_plan_change(request, tenant):
    """Process plan change"""
    try:
        new_plan = request.POST.get('plan')
        if not new_plan or new_plan not in ['starter', 'professional', 'enterprise']:
            messages.error(request, 'Invalid plan selected.')
            return redirect('tenants:subscription')
        
        if not tenant.stripe_subscription_id:
            messages.error(request, 'No active subscription to upgrade.')
            return redirect('tenants:subscription')
        
        # Get new price ID
        price_id = get_price_id_for_plan(new_plan)
        
        # Update subscription
        subscription = stripe.Subscription.modify(
            tenant.stripe_subscription_id,
            items=[{
                'id': tenant.stripe_subscription_id,
                'price': price_id
            }],
            proration_behavior='create_prorations'
        )
        
        # Update tenant
        old_plan = tenant.plan
        tenant.plan = new_plan
        tenant.subscription_status = subscription.status
        tenant.save()
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='plan_changed',
            details={
                'subscription_id': tenant.stripe_subscription_id,
                'old_plan': old_plan,
                'new_plan': new_plan
            }
        )
        
        messages.success(request, f'Plan changed to {new_plan.title()} successfully!')
        
    except stripe.error.StripeError as e:
        messages.error(request, f'Error changing plan: {str(e)}')
        logger.error(f"Stripe error: {str(e)}")
    except Exception as e:
        messages.error(request, f'An error occurred: {str(e)}')
        logger.error(f"Plan change error: {str(e)}")
    
    return redirect('tenants:subscription')


# apps/tenants/views.py - Updated settings_view

# apps/tenants/views.py - Fix the settings_view function

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

@login_required
def settings_update_view(request):
    """Update settings via AJAX"""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)
    
    tenant = request.user.tenant
    
    try:
        settings_obj = TenantSettings.objects.get(tenant=tenant)
    except TenantSettings.DoesNotExist:
        settings_obj = TenantSettings.objects.create(tenant=tenant)
    
    # Update specific settings
    setting_key = request.POST.get('key')
    setting_value = request.POST.get('value')
    
    if hasattr(settings_obj, setting_key):
        setattr(settings_obj, setting_key, setting_value)
        settings_obj.save()
        return JsonResponse({'success': True, 'message': 'Setting updated successfully'})
    elif hasattr(tenant, setting_key):
        setattr(tenant, setting_key, setting_value)
        tenant.save()
        return JsonResponse({'success': True, 'message': 'Setting updated successfully'})
    
    return JsonResponse({'success': False, 'message': 'Invalid setting key'}, status=400)


@login_required
def branding_settings_view(request):
    """Manage branding settings"""
    tenant = request.user.tenant
    
    if request.method == 'POST':
        # Update branding
        tenant.primary_color = request.POST.get('primary_color', tenant.primary_color)
        tenant.secondary_color = request.POST.get('secondary_color', tenant.secondary_color)
        tenant.accent_color = request.POST.get('accent_color', tenant.accent_color)
        
        if request.FILES.get('logo'):
            tenant.logo = request.FILES.get('logo')
        if request.FILES.get('favicon'):
            tenant.favicon = request.FILES.get('favicon')
        
        tenant.save()
        
        messages.success(request, 'Branding updated successfully!')
        return redirect('tenants:branding_settings')
    
    context = {
        'tenant': tenant,
        'title': 'Branding - PharmaPro'
    }
    return render(request, 'tenants/branding.html', context)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook_view(request):
    """Handle Stripe webhook events"""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {str(e)}")
        return JsonResponse({'error': 'Invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {str(e)}")
        return JsonResponse({'error': 'Invalid signature'}, status=400)
    
    # Handle the event
    event_type = event['type']
    event_data = event['data']['object']
    
    logger.info(f"Webhook event: {event_type} for {event_data.get('id')}")
    
    try:
        if event_type == 'customer.subscription.created':
            handle_subscription_created(event_data)
        elif event_type == 'customer.subscription.updated':
            handle_subscription_updated(event_data)
        elif event_type == 'customer.subscription.deleted':
            handle_subscription_deleted(event_data)
        elif event_type == 'invoice.payment_succeeded':
            handle_invoice_payment_succeeded(event_data)
        elif event_type == 'invoice.payment_failed':
            handle_invoice_payment_failed(event_data)
        elif event_type == 'customer.updated':
            handle_customer_updated(event_data)
    except Exception as e:
        logger.error(f"Webhook processing error: {str(e)}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)
    
    return JsonResponse({'status': 'success'})


def handle_subscription_created(event_data):
    """Handle subscription created event"""
    subscription_id = event_data['id']
    customer_id = event_data['customer']
    status = event_data['status']
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        tenant.stripe_subscription_id = subscription_id
        tenant.subscription_status = status
        tenant.subscription_start_date = timezone.now()
        tenant.save()
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='created',
            details={'subscription_id': subscription_id, 'status': status}
        )
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


def handle_subscription_updated(event_data):
    """Handle subscription updated event"""
    subscription_id = event_data['id']
    customer_id = event_data['customer']
    status = event_data['status']
    cancel_at_period_end = event_data.get('cancel_at_period_end', False)
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        tenant.subscription_status = status
        
        if cancel_at_period_end:
            tenant.subscription_status = 'cancelling'
        
        if status == 'canceled':
            tenant.subscription_status = 'cancelled'
            tenant.subscription_end_date = timezone.now()
        
        tenant.save()
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='updated',
            details={
                'subscription_id': subscription_id,
                'status': status,
                'cancel_at_period_end': cancel_at_period_end
            }
        )
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


def handle_subscription_deleted(event_data):
    """Handle subscription deleted event"""
    subscription_id = event_data['id']
    customer_id = event_data['customer']
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        tenant.subscription_status = 'cancelled'
        tenant.stripe_subscription_id = None
        tenant.subscription_end_date = timezone.now()
        tenant.save()
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='deleted',
            details={'subscription_id': subscription_id}
        )
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


def handle_invoice_payment_succeeded(event_data):
    """Handle successful invoice payment"""
    customer_id = event_data['customer']
    invoice_id = event_data['id']
    amount = event_data.get('amount_paid', 0)
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='payment_succeeded',
            details={
                'invoice_id': invoice_id,
                'amount': amount,
                'currency': event_data.get('currency', 'usd')
            }
        )
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


def handle_invoice_payment_failed(event_data):
    """Handle failed invoice payment"""
    customer_id = event_data['customer']
    invoice_id = event_data['id']
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='payment_failed',
            details={
                'invoice_id': invoice_id,
                'attempt_count': event_data.get('attempt_count', 0)
            }
        )
        
        # Update tenant status
        tenant.subscription_status = 'past_due'
        tenant.save()
        
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


def handle_customer_updated(event_data):
    """Handle customer updated event"""
    customer_id = event_data['id']
    
    try:
        tenant = Tenant.objects.get(stripe_customer_id=customer_id)
        
        # Update customer info if needed
        if 'email' in event_data:
            tenant.company_email = event_data['email']
        if 'name' in event_data:
            tenant.company_name = event_data['name']
        if 'address' in event_data:
            address = event_data['address']
            if address:
                tenant.company_address = f"{address.get('line1', '')}, {address.get('city', '')}, {address.get('state', '')} {address.get('postal_code', '')}"
        
        tenant.save()
        
    except Tenant.DoesNotExist:
        logger.error(f"Tenant not found for customer: {customer_id}")


@staff_member_required
def tenant_list_view(request):
    """Superuser view to list all tenants"""
    tenants = Tenant.objects.all().order_by('-created_at')
    
    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        tenants = tenants.filter(
            Q(name__icontains=search_query) |
            Q(company_name__icontains=search_query) |
            Q(slug__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    
    # Filter by status
    status_filter = request.GET.get('status', '')
    if status_filter:
        tenants = tenants.filter(subscription_status=status_filter)
    
    # Filter by plan
    plan_filter = request.GET.get('plan', '')
    if plan_filter:
        tenants = tenants.filter(plan=plan_filter)
    
    # Get statistics
    total_tenants = tenants.count()
    active_tenants = tenants.filter(subscription_status='active').count()
    trial_tenants = tenants.filter(subscription_status='trialing').count()
    
    paginator = Paginator(tenants, 20)
    page_number = request.GET.get('page', 1)
    tenants_page = paginator.get_page(page_number)
    
    context = {
        'tenants': tenants_page,
        'search_query': search_query,
        'status_filter': status_filter,
        'plan_filter': plan_filter,
        'total_tenants': total_tenants,
        'active_tenants': active_tenants,
        'trial_tenants': trial_tenants,
        'plan_choices': get_plan_choices(),
        'status_choices': get_status_choices(),
        'title': 'Manage Tenants - PharmaPro'
    }
    return render(request, 'tenants/list.html', context)


# apps/tenants/views.py - Update tenant_detail_view

@staff_member_required
def tenant_detail_view(request, tenant_id):
    """Superuser view to see tenant details"""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    # Get tenant statistics
    from accounts.models import User
    from inventory.models import Product
    from sales.models import Sale
    from django.db.models import Sum
    
    total_products = Product.objects.filter(tenant=tenant).count()
    total_sales = Sale.objects.filter(tenant=tenant).count()
    total_users = User.objects.filter(tenant=tenant).count()
    total_revenue = Sale.objects.filter(tenant=tenant).aggregate(
        total=Sum('total_amount')
    )['total'] or 0
    
    # Get all users for this tenant with their details
    users = User.objects.filter(tenant=tenant).order_by('-date_joined')
    
    # Get subscription logs
    subscription_logs = SubscriptionLog.objects.filter(
        tenant=tenant
    ).order_by('-created_at')[:20]
    
    # Get recent users
    recent_users = User.objects.filter(tenant=tenant).order_by('-date_joined')[:10]
    
    # Make sure superadmin context is preserved
    is_superadmin = request.user.is_superuser
    
    context = {
        'tenant': tenant,
        'total_products': total_products,
        'total_sales': total_sales,
        'total_users': total_users,
        'total_revenue': total_revenue,
        'users': users,
        'subscription_logs': subscription_logs,
        'recent_users': recent_users,
        'is_superadmin': is_superadmin,  # Pass this to template
        'title': f'{tenant.name} - PharmaPro'
    }
    return render(request, 'tenants/detail.html', context)

@staff_member_required
def tenant_suspend_view(request, tenant_id):
    """Superuser view to suspend a tenant"""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        
        tenant.subscription_status = 'suspended'
        tenant.save()
        
        # Cancel Stripe subscription if exists
        if tenant.stripe_subscription_id:
            try:
                stripe.Subscription.modify(
                    tenant.stripe_subscription_id,
                    cancel_at_period_end=True
                )
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error suspending tenant: {str(e)}")
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='suspended',
            details={
                'suspended_by': request.user.username,
                'reason': reason
            }
        )
        
        messages.success(request, f'{tenant.name} has been suspended.')
        return redirect('tenants:detail', tenant_id=tenant_id)
    
    context = {
        'tenant': tenant,
        'title': 'Suspend Tenant - PharmaPro'
    }
    return render(request, 'tenants/suspend.html', context)


@staff_member_required
def tenant_activate_view(request, tenant_id):
    """Superuser view to activate a tenant"""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        tenant.subscription_status = 'active'
        
        # Set subscription dates if not set
        if not tenant.subscription_start_date:
            tenant.subscription_start_date = timezone.now()
        if not tenant.subscription_end_date:
            tenant.subscription_end_date = timezone.now() + timezone.timedelta(days=30)
        
        tenant.save()
        
        # Reactivate Stripe subscription if exists
        if tenant.stripe_subscription_id:
            try:
                subscription = stripe.Subscription.modify(
                    tenant.stripe_subscription_id,
                    cancel_at_period_end=False
                )
                tenant.subscription_status = subscription.status
                tenant.save()
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error activating tenant: {str(e)}")
        
        SubscriptionLog.objects.create(
            tenant=tenant,
            action='activated',
            details={'activated_by': request.user.username}
        )
        
        messages.success(request, f'{tenant.name} has been activated.')
        return redirect('tenants:detail', tenant_id=tenant_id)
    
    context = {
        'tenant': tenant,
        'title': 'Activate Tenant - PharmaPro'
    }
    return render(request, 'tenants/activate.html', context)


@staff_member_required
def tenant_delete_view(request, tenant_id):
    """Superuser view to delete a tenant"""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    if request.method == 'POST':
        confirm = request.POST.get('confirm', '')
        if confirm != tenant.name:
            messages.error(request, 'Please type the tenant name correctly to confirm deletion.')
            return redirect('tenants:detail', tenant_id=tenant_id)
        
        # Cancel Stripe subscription
        if tenant.stripe_subscription_id:
            try:
                stripe.Subscription.delete(tenant.stripe_subscription_id)
            except stripe.error.StripeError as e:
                logger.error(f"Stripe error deleting subscription: {str(e)}")
        
        # Delete tenant (cascade will delete all related data)
        tenant_name = tenant.name
        tenant.delete()
        
        messages.success(request, f'Tenant {tenant_name} has been deleted.')
        return redirect('tenants:list')
    
    context = {
        'tenant': tenant,
        'title': 'Delete Tenant - PharmaPro'
    }
    return render(request, 'tenants/delete.html', context)


# Helper Functions

def get_price_id_for_plan(plan):
    """Get Stripe price ID for a plan"""
    price_ids = {
        'starter': settings.STRIPE_STARTER_PRICE_ID,
        'professional': settings.STRIPE_PROFESSIONAL_PRICE_ID,
        'enterprise': settings.STRIPE_ENTERPRISE_PRICE_ID,
    }
    return price_ids.get(plan, settings.STRIPE_STARTER_PRICE_ID)


def get_plan_details():
    """Get plan details with pricing"""
    return {
        'starter': {
            'name': 'Starter',
            'price': settings.STRIPE_STARTER_PRICE_AMOUNT,
            'features': ['Up to 10 users', '500 products', 'Basic reports'],
            'recommended': False
        },
        'professional': {
            'name': 'Professional',
            'price': settings.STRIPE_PROFESSIONAL_PRICE_AMOUNT,
            'features': ['Unlimited users', 'Unlimited products', 'Advanced reports', 'API access'],
            'recommended': True
        },
        'enterprise': {
            'name': 'Enterprise',
            'price': settings.STRIPE_ENTERPRISE_PRICE_AMOUNT,
            'features': ['All professional features', 'Priority support', 'Custom integrations'],
            'recommended': False
        }
    }


# apps/tenants/views.py - Update the get_timezone_choices function

def get_timezone_choices():
    """Get timezone choices using Django's timezone utilities"""
    import pytz
    # Or use Django's built-in timezone list
    from django.utils import timezone
    from django.conf import settings
    
    # Get all timezones from pytz
    try:
        import pytz
        return [(tz, tz) for tz in pytz.common_timezones]
    except ImportError:
        # Fallback to common timezones if pytz is not available
        common_timezones = [
            ('UTC', 'UTC'),
            ('America/New_York', 'Eastern Time (US & Canada)'),
            ('America/Chicago', 'Central Time (US & Canada)'),
            ('America/Denver', 'Mountain Time (US & Canada)'),
            ('America/Los_Angeles', 'Pacific Time (US & Canada)'),
            ('America/Phoenix', 'Arizona (MST)'),
            ('America/Anchorage', 'Alaska (AKST)'),
            ('America/Adak', 'Hawaii-Aleutian (HST)'),
            ('Pacific/Honolulu', 'Hawaii (HST)'),
            ('Europe/London', 'London (GMT)'),
            ('Europe/Paris', 'Paris (CET)'),
            ('Europe/Berlin', 'Berlin (CET)'),
            ('Europe/Moscow', 'Moscow (MSK)'),
            ('Africa/Nairobi', 'Nairobi (EAT)'),
            ('Africa/Johannesburg', 'Johannesburg (SAST)'),
            ('Asia/Dubai', 'Dubai (GST)'),
            ('Asia/Kolkata', 'India (IST)'),
            ('Asia/Shanghai', 'China (CST)'),
            ('Asia/Tokyo', 'Japan (JST)'),
            ('Asia/Singapore', 'Singapore (SGT)'),
            ('Australia/Sydney', 'Sydney (AEDT)'),
            ('Australia/Perth', 'Perth (AWST)'),
            ('Pacific/Auckland', 'New Zealand (NZDT)'),
        ]
        return common_timezones

def get_currency_choices():
    """Get currency choices"""
    return [
        ('USD', 'USD - US Dollar'),
        ('EUR', 'EUR - Euro'),
        ('GBP', 'GBP - British Pound'),
        ('NGN', 'NGN - Nigerian Naira'),
        ('KES', 'KES - Kenyan Shilling'),
        ('ZAR', 'ZAR - South African Rand'),
    ]


def get_date_format_choices():
    """Get date format choices"""
    return [
        ('Y-m-d', 'YYYY-MM-DD'),
        ('d-m-Y', 'DD-MM-YYYY'),
        ('m-d-Y', 'MM-DD-YYYY'),
        ('d/m/Y', 'DD/MM/YYYY'),
        ('m/d/Y', 'MM/DD/YYYY'),
    ]


def get_time_format_choices():
    """Get time format choices"""
    return [
        ('H:i:s', '24-hour (HH:MM:SS)'),
        ('h:i:s A', '12-hour (HH:MM:SS AM/PM)'),
    ]


def get_plan_choices():
    """Get plan choices for filter"""
    return [
        ('starter', 'Starter'),
        ('professional', 'Professional'),
        ('enterprise', 'Enterprise'),
    ]


def get_status_choices():
    """Get status choices for filter"""
    return [
        ('active', 'Active'),
        ('trialing', 'Trial'),
        ('past_due', 'Past Due'),
        ('cancelled', 'Cancelled'),
        ('suspended', 'Suspended'),
        ('cancelling', 'Cancelling'),
    ]