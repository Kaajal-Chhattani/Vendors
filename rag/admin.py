import logging

import requests
from django import forms
from django.contrib import admin
from django.core.cache import cache
from django.http import JsonResponse
from pypdf import PdfReader
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from unfold.admin import ModelAdmin, TabularInline
from django.template.loader import render_to_string
from rag.models import Document, DocumentChunk
from rag.service.cron_management import DocumentProcessor
from chat.service.document_notifications import notify_document_processed
from rag.service.kafka_events import publish_process_request
from rag.tasks import process_document_task, process_document_priority_task
from rag.service.document_runs import can_start, can_stop, start_document, stop_document
from rag.temporal.client import start_document_processing
from rag.temporal.run_status import get_run_status

logger = logging.getLogger(__name__)

STATUS_COLORS = {
    'pending': '#6b7280',
    'started': '#2563eb',
    'processed': '#16a34a',
    'error': '#dc2626',
}


class DocumentAdminForm(forms.ModelForm):
    url = forms.URLField(
        required=False,
        label="Or fetch from a URL",
        help_text="Provide only one of: file, URL, or pasted text.",
    )

    class Meta:
        model = Document
        fields = ['company', 'file', 'raw_text', 'url']
        widgets = {
            'raw_text': forms.Textarea(attrs={'rows': 6}),
        }
        labels = {
            'raw_text': 'Or paste text',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('file', 'raw_text'):
            if name in self.fields:
                self.fields[name].required = False

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk:
            return cleaned_data
        provided = [
            bool(cleaned_data.get('file')),
            bool(cleaned_data.get('url')),
            bool(cleaned_data.get('raw_text')),
        ]
        if sum(provided) != 1:
            raise forms.ValidationError(
                "Provide exactly one of: file, URL, or pasted text."
            )
        return cleaned_data


class DocumentChunkInline(TabularInline):
    model = DocumentChunk
    fields = ('chunk_index', 'content_preview', 'created_by', 'updated_by')
    readonly_fields = ('chunk_index', 'content_preview', 'created_by', 'updated_by')
    extra = 0
    can_delete = False
    show_change_link = True

    def content_preview(self, obj):
        """Show first 100 chars of content"""
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    form = DocumentAdminForm
    list_display = ('id', 'company', 'source_type', 'status_badge', 'process_actions', 'stop_start_actions', 'is_active', 'chunk_count', 'created_at', 'created_by', 'updated_by', 'run_status_button')
    list_filter = ('status', 'source_type', 'company', 'is_active', 'created_at')
    search_fields = ('raw_text', 'file')
    readonly_fields = ('source_type', 'status', 'created_at', 'updated_at')
    inlines = [DocumentChunkInline]
    list_per_page = 50
    actions = ['mark_as_pending']
    
    fieldsets = (
        (None, {'fields': ('company',)}),
        ('Add content (pick one)', {'fields': ('file', 'url', 'raw_text')}),
        ('Status', {'fields': ('source_type', 'status')}),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request.user.is_superuser:
            return fieldsets
        return tuple(
            (title, {**opts, 'fields': tuple(f for f in opts['fields'] if f != 'company')})
            for title, opts in fieldsets
        )

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault('company', request.user.current_company_id)
        return initial

    def status_badge(self, obj):
        html = render_to_string('rag/status_badge.html', {
            'color': STATUS_COLORS.get(obj.status, '#6b7280'),
            'label': obj.get_status_display(),
        })
        return mark_safe(html)
    status_badge.short_description = 'Status'

    def chunk_count(self, obj):
        return obj.chunks.count()
    chunk_count.short_description = 'Chunks'

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.current_company)

    def save_model(self, request, obj, form, change):
        if not obj.company_id:
            obj.company = request.user.current_company

        if not change:
            url = form.cleaned_data.get('url')
            uploaded_file = form.cleaned_data.get('file')

            if uploaded_file:
                obj.source_type = 'pdf'
                reader = PdfReader(uploaded_file)
                text = '\n'.join(page.extract_text() or '' for page in reader.pages)
            elif url:
                obj.source_type = 'scrape'
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                text = (response.text)
            else:
                obj.source_type = 'upload'
                text = obj.raw_text

            obj.raw_text = text
            obj.status = 'pending'
            obj.created_by = request.user
            obj.updated_by = request.user
            super().save_model(request, obj, form, change)
            # DocumentProcessor().create_chunks(obj, text)
        else:
            super().save_model(request, obj, form, change)
    
    def get_urls(self):
        custom_urls = [
            path('<int:doc_id>/process/', self.admin_site.admin_view(self.process_view), name='rag_document_process'),
            path('<int:doc_id>/process-celery/', self.admin_site.admin_view(self.process_celery_view), name='rag_document_process_celery'),
            path('<int:doc_id>/process-now/', self.admin_site.admin_view(self.process_now_view), name='rag_document_process_now'),
            path('<int:doc_id>/process-kafka/', self.admin_site.admin_view(self.process_kafka_view), name='rag_document_process_kafka'),
            path('<int:doc_id>/process-temporal/', self.admin_site.admin_view(self.process_temporal_view), name='rag_document_process_temporal'),
            path('<int:doc_id>/stop-temporal/', self.admin_site.admin_view(self.stop_temporal_view), name='rag_document_stop_temporal'),
            path('<int:doc_id>/start-temporal/', self.admin_site.admin_view(self.start_temporal_view), name='rag_document_start_temporal'),
            path('<int:doc_id>/dialog-stop/', self.admin_site.admin_view(self.dialog_stop_view), name='rag_document_dialog_stop'),
            path('<int:doc_id>/dialog-start/', self.admin_site.admin_view(self.dialog_start_view), name='rag_document_dialog_start'),
            path('<int:doc_id>/run-status/', self.admin_site.admin_view(self.run_status_view), name='rag_document_run_status'),
        ]
        return custom_urls + super().get_urls()

    def _get_pending_document(self, request, doc_id):
        qs = self.get_queryset(request)
        document = qs.filter(pk=doc_id, status='pending').first()
        if document is None:
            self.message_user(request, f'Document #{doc_id} is not pending.', level='warning')
        return document

    def process_view(self, request, doc_id):
        """Direct: process inside this web request, then notify chat directly."""
        document = self._get_pending_document(request, doc_id)
        if document:
            Document.objects.filter(pk=document.pk).update(processed_via='direct')
            for doc in DocumentProcessor().process_by_ids([document.pk]):
                notify_document_processed(doc)
                self.message_user(request, f'Document #{doc.pk} processed directly: {doc.get_status_display()}.')
        return redirect('/admin/rag/document/')

    def process_celery_view(self, request, doc_id):
        document = self._get_pending_document(request, doc_id)
        if document:
            Document.objects.filter(pk=document.pk).update(processed_via='celery')
            process_document_task.delay(document.pk)
            self.message_user(request, f'Document #{document.pk} queued on Celery.')
        return redirect('/admin/rag/document/')

    def process_now_view(self, request, doc_id):
        document = self._get_pending_document(request, doc_id)
        if document:
            Document.objects.filter(pk=document.pk).update(processed_via='celery_priority')
            process_document_priority_task.delay(document.pk)
            self.message_user(request, f'Document #{document.pk} queued on Celery priority queue.')
        return redirect('/admin/rag/document/')

    def process_kafka_view(self, request, doc_id):
        document = self._get_pending_document(request, doc_id)
        if document:
            Document.objects.filter(pk=document.pk).update(processed_via='kafka')
            publish_process_request(document)
            self.message_user(request, f'Document #{document.pk} sent to Kafka for processing.')
        return redirect('/admin/rag/document/')

    def process_temporal_view(self, request, doc_id):
        document = self._get_pending_document(request, doc_id)
        if document:
            try:
                started = start_document_processing(document.pk)
            except Exception:
                logger.exception('Could not start the Temporal workflow for document %s', document.pk)
                self.message_user(request, f'Could not reach Temporal for document #{document.pk}. Is the server running?', level='error')
            else:
                Document.objects.filter(pk=document.pk).update(processed_via='temporal')
                cache.set(self.TEMPORAL_SENT_KEY.format(document.pk), True, self.TEMPORAL_SENT_TTL)
                if started:
                    self.message_user(request, f'Document #{document.pk} sent to Temporal for processing.')
                else:
                    self.message_user(request, f'Document #{document.pk} is already being processed by Temporal.', level='warning')
        return redirect('/admin/rag/document/')

    def stop_temporal_view(self, request, doc_id):
        """Cancel the document's Temporal run and put it back to pending."""
        document = self.get_queryset(request).filter(pk=doc_id).first()
        ok, message = stop_document(document) if document else (False, f'Document #{doc_id} not found.')
        if ok:
            cache.delete(self.TEMPORAL_SENT_KEY.format(document.pk))
        self.message_user(request, message, level='info' if ok else 'warning')
        return redirect('/admin/rag/document/')

    def start_temporal_view(self, request, doc_id):
        """(Re)start the Temporal workflow for a stopped, failed, pending or text-only document."""
        document = self.get_queryset(request).filter(pk=doc_id).first()
        ok, message = start_document(document) if document else (False, f'Document #{doc_id} not found.')
        if ok:
            cache.set(self.TEMPORAL_SENT_KEY.format(document.pk), True, self.TEMPORAL_SENT_TTL)
        self.message_user(request, message, level='info' if ok else 'warning')
        return redirect('/admin/rag/document/')

    def _dialog_document(self, document):
        return {
            'id': document.pk,
            'status': document.get_status_display(),
            'via': self.PROCESSED_VIA_LABELS.get(document.processed_via, '-'),
            'chunks': document.chunks.count(),
            'can_start': can_start(document),
            'can_stop': can_stop(document),
            'start_url': reverse('admin:rag_document_dialog_start', args=[document.pk]),
            'stop_url': reverse('admin:rag_document_dialog_stop', args=[document.pk]),
        }

    def run_status_view(self, request, doc_id):
        """JSON for the run-status dialog: the document's summary plus the latest Temporal run."""
        if not self.has_view_permission(request):
            return JsonResponse({'message': 'You do not have permission to view this.'}, status=403)
        document = self.get_queryset(request).filter(pk=doc_id).first()
        if document is None:
            return JsonResponse({'message': f'Document #{doc_id} not found.'}, status=404)
        info = self._dialog_document(document)
        try:
            run = get_run_status(doc_id)
        except Exception:
            logger.exception('Could not read the Temporal run for document %s', doc_id)
            return JsonResponse({'message': 'Temporal is unreachable. Is the server running?', 'document': info}, status=502)
        if run is None:
            return JsonResponse({'message': 'No Temporal run for this document.', 'document': info})
        return JsonResponse({**run, 'document': info})

    def _dialog_action(self, request, doc_id, action):
        if request.method != 'POST':
            return JsonResponse({'message': 'POST required.'}, status=405)
        document = self.get_queryset(request).filter(pk=doc_id).first()
        if document is None:
            return JsonResponse({'message': f'Document #{doc_id} not found.'}, status=404)
        ok, message = action(document)
        if ok:
            key = self.TEMPORAL_SENT_KEY.format(document.pk)
            cache.set(key, True, self.TEMPORAL_SENT_TTL) if action is start_document else cache.delete(key)
        return JsonResponse({'ok': ok, 'message': message}, status=200 if ok else 409)

    def dialog_stop_view(self, request, doc_id):
        return self._dialog_action(request, doc_id, stop_document)

    def dialog_start_view(self, request, doc_id):
        return self._dialog_action(request, doc_id, start_document)

    def run_status_button(self, obj):
        if obj.processed_via not in ('temporal', 'temporal_extract'):
            return ''
        return render_to_string('rag/run_status_button.html', {
            'url': reverse('admin:rag_document_run_status', args=[obj.pk]),
        })
    run_status_button.short_description = 'Run'

    TEMPORAL_SENT_KEY = 'rag_temporal_sent_{}'
    TEMPORAL_SENT_TTL = 300  # seconds to show "Temporal" instead of the dropdown while the worker claims the document

    SELECT_STYLE = "padding:4px 8px; border-radius:6px; font-size:12px; font-weight:600;"

    PROCESS_BUTTONS = (
        ('process', 'Process', '#2563eb'),
        ('process-celery', 'Celery', '#16a34a'),
        ('process-now', 'Celery – priority', '#d97706'),
        ('process-kafka', 'Kafka', '#7c3aed'),
        ('process-temporal', 'Temporal', '#0891b2'),
    )

    PROCESSED_VIA_LABELS = {
        'direct': 'Process',
        'celery': 'Celery',
        'celery_priority': 'Celery – priority',
        'kafka': 'Kafka',
        'temporal': 'Temporal',
        'temporal_extract': 'Temporal (text only)',
    }

    def process_actions(self, obj):
        if obj.status != 'pending':
            return self.PROCESSED_VIA_LABELS.get(obj.processed_via, '-')
        if cache.get(self.TEMPORAL_SENT_KEY.format(obj.pk)):
            return 'Temporal'
        options = format_html_join(
            '',
            '<option value="/admin/rag/document/{}/{}/">{}</option>',
            ((obj.pk, action, label) for action, label, _color in self.PROCESS_BUTTONS),
        )
        return format_html(
            '<select style="{}" onchange="'
            "if (!this.value) return; "
            "if (confirm('Process this document with ' + this.options[this.selectedIndex].text + '?')) "
            "{{ window.location = this.value; }} else {{ this.value = ''; }}"
            '">'
            '<option value="">Choose...</option>{}</select>',
            self.SELECT_STYLE,
            options,
        )
    process_actions.short_description = 'Process with'

    def stop_start_actions(self, obj):
        if can_stop(obj):
            action, label, color = 'stop-temporal', 'Stop', '#dc2626'
        elif can_start(obj):
            action, label, color = 'start-temporal', 'Start', '#16a34a'
        else:
            return ''
        return format_html(
            '<a href="/admin/rag/document/{}/{}/" style="background:{};color:#fff;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none;" '
            "onclick=\"return confirm('{} this document on Temporal?');\">{}</a>",
            obj.pk, action, color, label, label,
        )
    stop_start_actions.short_description = 'Temporal'

    def mark_as_pending(self, request, queryset):
        """Reset documents to pending status"""
        updated = queryset.update(status='pending')
        self.message_user(request, f'{updated} document(s) marked as pending.')
    mark_as_pending.short_description = 'Mark as pending'


@admin.register(DocumentChunk)
class DocumentChunkAdmin(ModelAdmin):
    list_display = ('id', 'document', 'chunk_index', 'content_preview', 'company', 'is_active', 'created_at')
    list_filter = ('company', 'document__status', 'is_active', 'created_at')
    search_fields = ('content', 'document__id')
    readonly_fields = ('document', 'content', 'embedding', 'chunk_index', 'company', 'created_by', 'updated_by', 'created_at', 'updated_at')
    list_per_page = 50
    
    fieldsets = (
        ('Chunk Information', {
            'fields': ('document', 'chunk_index', 'content', 'company')
        }),
        ('Embedding', {
            'fields': ('embedding',),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'updated_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def content_preview(self, obj):
        """Show first 100 chars of content"""
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content
    content_preview.short_description = 'Content Preview'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(company=request.user.current_company)