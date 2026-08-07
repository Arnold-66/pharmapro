# apps/accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Authentication
    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('logout/', views.logout_view, name='logout'),
    path('verify-email/', views.verify_email_view, name='verify_email'),
    path('password-reset/', views.password_reset_view, name='password_reset'),
    path('password-reset/done/', views.password_reset_done_view, name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', views.password_reset_confirm_view, name='password_reset_confirm'),

    # Landing and Dashboard
    path('', views.landing_view, name='landing'),
    path('dashboard/', views.dashboard_view, name='dashboard'),

    path('<slug:tenant_slug>/dashboard/', views.tenant_dashboard_view, name='tenant_dashboard'),

    # Profile
    path('profile/', views.profile_view, name='profile'),
    path('check-username/', views.check_username_view, name='check_username'),
    path('profile/update/', views.profile_update_view, name='profile_update'),
    path('profile/change-password/', views.change_password_view, name='change_password'),
    path('settings/', views.settings_view, name='settings'),  # This causes conflict
    
    # User Management
    path('users/', views.user_list_view, name='user_list'),
    path('users/create/', views.user_create_view, name='user_create'),
    path('users/<uuid:user_id>/', views.user_detail_view, name='user_detail'),
    path('users/<uuid:user_id>/edit/', views.user_edit_view, name='user_edit'),
    path('users/<uuid:user_id>/delete/', views.user_delete_view, name='user_delete'),
    path('users/<uuid:user_id>/toggle-active/', views.user_toggle_active_view, name='user_toggle_active'),
    
    path('admin/users/create/', views.superuser_user_create_view, name='superuser_user_create'),
    path('superuser/organizations/create/', views.superuser_tenant_create_view, name='superuser_tenant_create'),

    path('admin/users/', views.superuser_user_list_view, name='superuser_users'),
    path('admin/users/<uuid:user_id>/', views.superuser_user_detail_view, name='superuser_user_detail'),
    path('admin/users/<uuid:user_id>/toggle-active/', views.superuser_user_toggle_active_view, name='superuser_user_toggle_active'),
    path('admin/users/<uuid:user_id>/make-admin/', views.superuser_user_make_admin_view, name='superuser_user_make_admin'),
    path('admin/users/<uuid:user_id>/make-superadmin/', views.superuser_user_make_superadmin_view, name='superuser_user_make_superadmin'),
    path('admin/users/<uuid:user_id>/delete/', views.superuser_user_delete_view, name='superuser_user_delete'),


    path('admin/subscriptions/', views.superuser_subscription_view, name='superuser_subscription'),
    path('admin/subscriptions/<uuid:tenant_id>/renew/', views.superuser_subscription_renew, name='superuser_subscription_renew'),
    path('admin/subscriptions/<uuid:tenant_id>/cancel/', views.superuser_subscription_cancel, name='superuser_subscription_cancel'),
    
    # Superadmin System Settings
    path('admin/settings/', views.superuser_settings_view, name='superuser_settings'),
    path('admin/settings/reset/', views.superuser_settings_reset, name='superuser_settings_reset'),
    
    # Superadmin System Logs
    path('admin/logs/', views.superuser_logs_view, name='superuser_logs'),
    path('admin/logs/clear/', views.superuser_clear_logs, name='superuser_clear_logs'),


    # Online Status
    path('users/online/', views.online_users_view, name='online_users'),
    path('users/online/data/', views.get_online_users, name='get_online_users'),
    path('users/update-status/', views.update_user_online_status, name='update_user_online_status'),
    
    # Notifications
    path('notifications/', views.notifications_view, name='notifications'),
    path('notification/<uuid:notification_id>/', views.notification_detail_view, name='notification_detail'),
    path('notification/<uuid:notification_id>/mark-read/', views.notification_mark_read_view, name='notification_mark_read'),
    path('notification/mark-all-read/', views.notification_mark_all_read_view, name='notification_mark_all_read'),
    path('notification/<uuid:notification_id>/delete/', views.notification_delete_view, name='notification_delete'),
    path('api/notifications/', views.get_notifications_api, name='get_notifications_api'),
]