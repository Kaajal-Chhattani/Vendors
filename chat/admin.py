from django.contrib import admin
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline

from auth.permissions import is_admin, scope_queryset
from .models import Conversation, Message,Agent,ToolDefinition,Order

class CompanyFilterMixin:
    """Show the company sidebar filter to admins (superusers) only."""
    def get_list_filter(self, request):
        filters = super().get_list_filter(request)
        if is_admin(request.user):
            return filters
        return [f for f in filters if f != 'company']


ORDER_STATUS_COLORS = {
    'processing': '#2563eb',
    'shipped': '#ca8a04',
    'delivered': '#16a34a',
    'cancelled': '#dc2626',
}


class MessageInline(TabularInline):
    model = Message
    fields = ('role', 'content')
    readonly_fields = ('role', 'content')
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

@admin.register(Agent)
class AgentAdmin(CompanyFilterMixin, ModelAdmin):
    list_display = ('label', 'agent_type','company', 'created_by', 'updated_by', 'is_active')
    list_filter = ('company', 'is_active', 'created_at')
    search_fields = ('label', 'agent_type', 'description', 'prompt')
    readonly_fields = ('company', 'created_by', 'updated_by', 'created_at', 'updated_at')
    list_per_page = 50
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('company', 'label', 'agent_type', 'is_active')
        }),
        ('Configuration', {
            'fields': ('description', 'prompt', 'workflow_json')
        }),
        ('Audit Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)

    def save_model(self, request, obj, form, change):
        if not obj.company_id:
            obj.company = request.user.current_company
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ToolDefinition)
class ToolDefinitionAdmin(CompanyFilterMixin, ModelAdmin):
    list_display = ('name', 'company', 'http_method', 'created_by', 'updated_by', 'is_active')
    list_filter = ('company', 'http_method', 'is_active', 'created_at')
    search_fields = ('name', 'description', 'endpoint_url')
    filter_horizontal = ('agents',)
    readonly_fields = ('company', 'created_by', 'updated_by', 'created_at', 'updated_at')
    list_per_page = 50
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('company', 'name', 'description', 'is_active')
        }),
        ('Configuration', {
            'fields': ('endpoint_url', 'http_method', 'args_schema', 'workflow_json')
        }),
        ('Agent Assignment', {
            'fields': ('agents',)
        }),
        ('Audit Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)

    def save_model(self, request, obj, form, change):
        if not obj.company_id:
            obj.company = request.user.current_company
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Conversation)
class ConversationAdmin(CompanyFilterMixin, ModelAdmin):
    list_display = ('title', 'user', 'company','summary','agent_type', 'is_active', 'session_id', 'created_at', 'created_by', 'updated_by')
    list_filter = ('agent_type', 'company', 'is_active', 'created_at')
    search_fields = ('title', 'summary', 'session_id', 'user__email')
    readonly_fields = ('session_id', 'created_at', 'updated_at')
    inlines = [MessageInline]
    list_per_page = 50

    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)
    
    fieldsets = (
        ('Conversation Details', {
            'fields': ('title', 'user', 'company', 'agent_type', 'session_id')
        }),
        ('Summary', {
            'fields': ('summary',)
        }),
        ('Audit Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Message)
class MessageAdmin(CompanyFilterMixin, ModelAdmin):
    list_display = ('id', 'conversation', 'role', 'content_preview', 'user','session_id','company', 'is_active','created_at','created_by','updated_by')
    list_filter = ('role', 'company', 'is_active', 'created_at')
    search_fields = ('content', 'conversation__title', 'user__email', 'session_id')
    readonly_fields = [f.name for f in Message._meta.fields] + ['created_at', 'updated_at']
    list_per_page = 50

    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)
    
    fieldsets = (
        ('Message Details', {
            'fields': ('conversation', 'role', 'content', 'file', 'user', 'session_id', 'company')
        }),
        ('Audit Information', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def content_preview(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content Preview'

    def has_add_permission(self, request):
        return False


@admin.register(Order)
class OrderAdmin(CompanyFilterMixin, ModelAdmin):
    list_display = ('order_number', 'customer_name', 'status', 'company', 'is_active', 'created_by', 'updated_by')
    list_filter = ('status', 'company', 'is_active')
    readonly_fields = ('company', 'created_by', 'updated_by')

    def get_queryset(self, request):
        return scope_queryset(super().get_queryset(request), request.user)

    def save_model(self, request, obj, form, change):
        if not obj.company_id:
            obj.company = request.user.current_company
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
