# apps/reports/models.py
from django.db import models
from django.contrib.auth import get_user_model
from tenants.models import Tenant
import uuid

User = get_user_model()

class Report(models.Model):
    TYPES = [
        ('sales', 'Sales Report'),
        ('inventory', 'Inventory Report'),
        ('supplier', 'Supplier Report'),
        ('financial', 'Financial Report'),
        ('custom', 'Custom Report'),
    ]
    
    FORMATS = [
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('csv', 'CSV'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='reports')
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=TYPES)
    format = models.CharField(max_length=10, choices=FORMATS, default='pdf')
    filters = models.JSONField(default=dict)
    parameters = models.JSONField(default=dict)
    file = models.FileField(upload_to='reports/', blank=True, null=True)
    is_scheduled = models.BooleanField(default=False)
    schedule_frequency = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ], blank=True, null=True)
    last_generated = models.DateTimeField(null=True, blank=True)
    next_generation = models.DateTimeField(null=True, blank=True)
    parameters = models.JSONField(default=dict, blank=True)  # Store report data for preview
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_reports')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'reports_report'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.type}"

class ReportTemplate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='report_templates')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    template = models.JSONField()  # Template structure
    is_default = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='report_templates')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'reports_templates'
        ordering = ['name']
        unique_together = ['tenant', 'name']
    
    def __str__(self):
        return self.name