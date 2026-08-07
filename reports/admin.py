# apps/reports/admin.py

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import reverse
from django.contrib.admin import display

from .models import Report, ReportTemplate


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):

    list_display = [
        'id',
        'name',
        'tenant_name',
        'type_badge',
        'format_badge',
        'status_badge',
        'created_by_name',
        'created_at_display',
        'file_size_display',
        'actions_links'
    ]

    list_filter = [
        'type',
        'format',
        'is_scheduled',
        'schedule_frequency',
        'tenant',
        'created_at',
        'last_generated',
        ('created_by', admin.RelatedOnlyFieldListFilter),
    ]

    search_fields = [
        'name',
        'id',
        'created_by__username',
        'created_by__email',
        'created_by__first_name',
        'created_by__last_name',
        'tenant__name',
        'tenant__company_name',
    ]

    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
        'last_generated',
        'file_size_display',
        'parameters_preview',
        'filters_preview',
    ]

    date_hierarchy = 'created_at'

    ordering = ['-created_at']

    list_per_page = 25


    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.select_related(
            'tenant',
            'created_by'
        )


    @display(description='Tenant', ordering='tenant__name')
    def tenant_name(self, obj):

        if obj.tenant:

            url = reverse(
                'admin:tenants_tenant_change',
                args=[obj.tenant.id]
            )

            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.tenant.company_name or obj.tenant.name
            )

        return format_html(
            '<span style="color:#999;">{}</span>',
            '-'
        )



    @display(description='Created By')
    def created_by_name(self, obj):

        if obj.created_by:

            url = reverse(
                'admin:accounts_user_change',
                args=[obj.created_by.id]
            )

            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.created_by.get_full_name()
                or obj.created_by.username
            )

        return format_html(
            '<span style="color:#999;">{}</span>',
            'System'
        )



    @display(description='Created')
    def created_at_display(self, obj):

        diff = timezone.now() - obj.created_at

        days = diff.days
        hours = diff.seconds // 3600


        text = (
            f'{days}d {hours}h ago'
            if days > 0
            else f'{hours}h ago'
        )


        return format_html(
            '<span title="{}">{}</span>',
            obj.created_at.strftime(
                '%Y-%m-%d %H:%M'
            ),
            text
        )



    @display(description='Type')
    def type_badge(self, obj):

        colors = {
            'sales': '#17a2b8',
            'inventory': '#28a745',
            'supplier': '#ffc107',
            'financial': '#dc3545',
            'custom': '#6c757d',
        }

        color = colors.get(
            obj.type,
            '#6c757d'
        )


        label = dict(
            Report.TYPES
        ).get(
            obj.type,
            obj.type
        )


        return format_html(
            '''
            <span style="
                background:{};
                color:white;
                padding:3px 15px;
                border-radius:12px;
                display:inline-block;
                min-width:120px;
                text-align:center;
            ">
                {}
            </span>
            ''',
            color,
            label
        )


    @display(description='Format')
    def format_badge(self, obj):

        colors = {
            'pdf':'#dc3545',
            'excel':'#28a745',
            'csv':'#17a2b8'
        }


        return format_html(
            '<span style="background:{};color:white;padding:3px 10px;border-radius:5px;">{}</span>',
            colors.get(
                obj.format,
                '#6c757d'
            ),
            obj.format.upper()
        )



    @display(description='Status')
    def status_badge(self, obj):

        if obj.file:

            return format_html(
                '<span style="background:#28a745;color:white;padding:3px 10px;border-radius:12px;">{}</span>',
                'Ready'
            )


        if obj.is_scheduled:

            return format_html(
                '<span style="background:#17a2b8;color:white;padding:3px 10px;border-radius:12px;">{}</span>',
                '⏰ Scheduled'
            )


        return format_html(
            '<span style="background:#ffc107;color:#222;padding:3px 10px;border-radius:12px;">{}</span>',
            '⏳ Pending'
        )



    @display(description='File Size')
    def file_size_display(self,obj):

        if obj.file:

            size = obj.file.size

            if size < 1024:
                return f"{size} B"

            if size < 1024*1024:
                return f"{size/1024:.1f} KB"

            return f"{size/(1024*1024):.1f} MB"


        return "-"



    @display(description='Filters Preview')
    def filters_preview(self,obj):

        if obj.filters:

            import json

            html = json.dumps(
                obj.filters,
                indent=2,
                default=str
            )

            return format_html(
                '<pre>{}</pre>',
                html
            )


        return format_html(
            '<span>{}</span>',
            'No filters applied'
        )



    @display(description='Parameters Preview')
    def parameters_preview(self,obj):

        if obj.parameters:

            import json

            html = json.dumps(
                obj.parameters,
                indent=2,
                default=str
            )


            return format_html(
                '<pre>{}</pre>',
                html
            )


        return format_html(
            '<span>{}</span>',
            'No parameters available'
        )



    @display(description='Actions')
    def actions_links(self,obj):

        links=[]

        if obj.file:

            links.append(
                f'<a href="{obj.file.url}" target="_blank">View</a>'
            )

            links.append(
                f'<a href="{obj.file.url}" download>Download</a>'
            )


        if links:

            return format_html(
                '{}',
                " | ".join(links)
            )


        return format_html(
            '<span>{}</span>',
            '-'
        )
    
@admin.register(ReportTemplate)
class ReportTemplateAdmin(admin.ModelAdmin):

    list_display = [
        'name',
        'tenant_name',
        'is_default_badge',
        'created_by_name',
        'created_at_display',
        'template_preview'
    ]

    list_filter = [
        'is_default',
        'tenant',
        'created_at',
    ]

    search_fields = [
        'name',
        'description',
        'tenant__name',
        'tenant__company_name',
        'created_by__username',
        'created_by__email',
    ]

    readonly_fields = [
        'id',
        'created_at',
        'updated_at',
        'template_preview',
    ]

    list_per_page = 20

    ordering = [
        'name'
    ]


    def get_queryset(self, request):

        queryset = super().get_queryset(request)

        return queryset.select_related(
            'tenant',
            'created_by'
        )



    @display(
        description='Tenant',
        ordering='tenant__name'
    )
    def tenant_name(self,obj):

        if obj.tenant:

            url = reverse(
                'admin:tenants_tenant_change',
                args=[obj.tenant.id]
            )


            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.tenant.company_name or obj.tenant.name
            )


        return format_html(
            '<span style="color:#999;">{}</span>',
            '-'
        )



    @display(
        description='Created By',
        ordering='created_by__username'
    )
    def created_by_name(self,obj):

        if obj.created_by:

            url = reverse(
                'admin:accounts_user_change',
                args=[obj.created_by.id]
            )


            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.created_by.get_full_name()
                or obj.created_by.username
            )


        return format_html(
            '<span style="color:#999;">{}</span>',
            'System'
        )



    @display(
        description='Created',
        ordering='created_at'
    )
    def created_at_display(self,obj):

        diff = timezone.now() - obj.created_at


        days = diff.days
        hours = diff.seconds // 3600


        text = (
            f'{days}d {hours}h ago'
            if days > 0
            else f'{hours}h ago'
        )


        return format_html(
            '<span title="{}">{}</span>',
            obj.created_at.strftime(
                '%Y-%m-%d %H:%M'
            ),
            text
        )



    @display(description='Default')
    def is_default_badge(self,obj):

        if obj.is_default:

            return format_html(
                '<span style="background:#28a745;color:white;padding:3px 10px;border-radius:12px;">{}</span>',
                '⭐ Default'
            )


        return format_html(
            '<span style="background:#6c757d;color:white;padding:3px 10px;border-radius:12px;">{}</span>',
            'Custom'
        )



    @display(description='Template Preview')
    def template_preview(self,obj):

        if obj.template:

            import json


            preview = obj.template.copy()


            if isinstance(preview,dict):

                preview = dict(
                    list(preview.items())[:10]
                )


            data = json.dumps(
                preview,
                indent=2,
                default=str
            )


            return format_html(
                '<pre style="background:#f8f9fa;padding:10px;">{}</pre>',
                data
            )



        return format_html(
            '<span style="color:#999;">{}</span>',
            'No template data'
        )



    # ACTIONS


    @admin.action(description="Set selected templates as default")
    def set_as_default(self,request,queryset):

        for template in queryset:

            ReportTemplate.objects.filter(
                tenant=template.tenant
            ).update(
                is_default=False
            )


            template.is_default=True

            template.save()


        self.message_user(
            request,
            f"{queryset.count()} template(s) updated."
        )



    @admin.action(description="Remove default status")
    def remove_default_status(self,request,queryset):

        queryset.update(
            is_default=False
        )


        self.message_user(
            request,
            f"{queryset.count()} template(s) updated."
        )



    @admin.action(description="Duplicate templates")
    def duplicate_template(self,request,queryset):

        count=0


        for template in queryset:

            ReportTemplate.objects.create(

                tenant=template.tenant,

                name=f"{template.name} Copy",

                description=template.description,

                template=template.template,

                created_by=request.user

            )

            count+=1



        self.message_user(
            request,
            f"{count} template(s) duplicated."
        )



    @admin.action(description="Delete templates without tenant")
    def delete_without_tenant(self,request,queryset):

        deleted, _ = queryset.filter(
            tenant__isnull=True
        ).delete()


        self.message_user(
            request,
            f"{deleted} template(s) deleted."
        )