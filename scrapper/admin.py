from django.contrib import admin
from django.utils.safestring import mark_safe
from django.template.loader import render_to_string
from unfold.admin import ModelAdmin, TabularInline
from .models import ScrapperItem, ScrapperJob

STATUS_COLORS = {
    'pending': '#6b7280',
    'in_progress': '#2563eb',
    'completed': '#16a34a',
    'failed': '#dc2626',
}


class ScrapperItemInline(TabularInline):
    model = ScrapperItem
    fields = ('parsed_data', 'created_at')
    readonly_fields = ('parsed_data', 'created_at')
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ScrapperJob)
class ScrapperJobAdmin(ModelAdmin):
    list_display = ('id', 'source_url', 'status_badge', 'company', 'is_active', 'started_at', 'completed_at', 'created_by', 'updated_by')
    list_filter = ('status', 'company', 'is_active', 'created_at')
    search_fields = ('source_url', 'error_message')
    readonly_fields = ('company', 'created_by', 'updated_by', 'started_at', 'completed_at')
    inlines = [ScrapperItemInline]
    list_per_page = 50
    
    fieldsets = (
        ('Job Information', {
            'fields': ('company', 'source_url', 'status')
        }),
        ('Timing', {
            'fields': ('started_at', 'completed_at')
        }),
        ('Error Details', {
            'fields': ('error_message',),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def status_badge(self, obj):
        html = f'<span style="background-color:{STATUS_COLORS.get(obj.status, "#6b7280")}; color:white; padding:2px 10px; border-radius:9999px; font-size:12px; font-weight:600;">{obj.get_status_display()}</span>'
        return mark_safe(html)
    status_badge.short_description = 'Status'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.current_company)

    def save_model(self, request, obj, form, change):
        if not obj.company_id:
            obj.company = request.user.current_company
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ScrapperItem)
class ScrapperItemAdmin(ModelAdmin):
    list_display = ('id', 'job', 'company', 'is_active', 'created_at', 'created_by', 'updated_by')
    list_filter = ('company', 'is_active', 'created_at')
    search_fields = ('parsed_data',)
    readonly_fields = ('company', 'job', 'parsed_data', 'created_by', 'updated_by')
    list_per_page = 50

    fieldsets = (
        ('Item Information', {
            'fields': ('company', 'job')
        }),
        ('Data', {
            'fields': ('parsed_data',)
        }),
        ('Audit', {
            'fields': ('created_by', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.current_company)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
