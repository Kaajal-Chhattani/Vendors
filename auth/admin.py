from django.contrib import admin
from django.contrib.auth.hashers import make_password
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import User


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ('email', 'full_name', 'is_staff', 'is_superuser', 'current_company', 'company_count', 'last_login')
    list_filter = ('is_staff', 'is_superuser', 'current_company', 'company')
    search_fields = ('email', 'first_name', 'last_name')
    filter_horizontal = ('company', 'groups', 'user_permissions')
    readonly_fields = ('last_login',)
    list_per_page = 50
    
    fieldsets = (
        ('Personal Information', {
            'fields': ('email', 'first_name', 'last_name', 'password')
        }),
        ('Company Association', {
            'fields': ('current_company', 'company')
        }),
        ('Permissions', {
            'fields': ('is_staff', 'is_superuser', 'groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        ('Important Dates', {
            'fields': ('last_login',),
            'classes': ('collapse',)
        }),
    )
    
    def full_name(self, obj):
        """Display full name or email if name is empty"""
        name = f"{obj.first_name} {obj.last_name}".strip()
        return name if name else format_html('<em>{}</em>', obj.email)
    full_name.short_description = 'Name'
    full_name.admin_order_field = 'first_name'
    
    def company_count(self, obj):
        """Display number of associated companies"""
        count = obj.company.count()
        return format_html('<span style="color: {};">{}</span>', 
                          '#16a34a' if count > 0 else '#dc2626', count)
    company_count.short_description = 'Companies'
    
    def save_model(self, request, obj, form, change):
        if 'password' in form.changed_data:
            obj.password = make_password(obj.password)
        super().save_model(request, obj, form, change)
