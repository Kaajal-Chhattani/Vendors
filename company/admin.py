from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import Company


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ('name', 'slug', 'company_type', 'is_active', 'user_count', 'created_at')
    list_filter = ('company_type', 'is_active', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('created_at', 'updated_at', 'created_by', 'updated_by')
    list_per_page = 50
    
    fieldsets = (
        ('Company Information', {
            'fields': ('name', 'slug', 'company_type')
        }),
        ('Audit Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def user_count(self, obj):
        """Display number of users in this company"""
        count = obj.users.count()
        return format_html('<span style="color: {};">{}</span>', 
                          '#16a34a' if count > 0 else '#6b7280', count)
    user_count.short_description = 'Users'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(id__in=request.user.company.values_list('id', flat=True))