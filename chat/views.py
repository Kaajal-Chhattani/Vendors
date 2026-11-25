import hmac
import json
import re

from django.http import Http404
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from auth.permissions import is_admin, scope_queryset
from chat.models import AGENT_CHOICES
from chat.models import Agent
from chat.models import Conversation
from chat.models import HTTP_METHOD_CHOICES
from chat.models import Message
from chat.models import Order
from chat.models import ToolDefinition
from chat.service.langgraph_agents import AGENTS, get_agent_choices, is_valid_agent_type

# from chat.service.langgraph_agents import get_agent_graph
from chat.service import process_runs
from chat.service.commands import handle_command
from chat.service.llm import generate_reply
from chat.service.summary import update_summary
from chat.service.conversation import get_conversation_by_session_id, conversation_file_paths, file_display_name
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import FileResponse, JsonResponse
from django.urls import reverse
from rag.models import Document
from rag.service.document_runs import can_start, can_stop, start_document, stop_document
from rag.temporal.client import get_extract_text, stop_pdf_extract
from rag.temporal.run_status import get_extract_run_status, get_run_status, summarize_run



def _name_key(name):
    """'TNA Performance.csv' and 'TNA_Performance.csv' compare equal."""
    return re.sub(r'[^a-z0-9]', '', (name or '').lower())


SIDEBAR_GROUPS = [
    ('today', 'Today'),
    ('yesterday', 'Yesterday'),
    ('week', 'Previous 7 days'),
    ('older', 'Older'),
]


def _sidebar_group_key(updated_at):
    days = (timezone.localdate() - timezone.localtime(updated_at).date()).days
    if days <= 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    if days <= 7:
        return 'week'
    return 'older'


class ChatPageView(LoginRequiredMixin, View):
    def get(self, request, agent_type=None):
        if agent_type and not is_valid_agent_type(agent_type):
            raise Http404('Unknown agent')
        conversations=scope_queryset(Conversation.objects.all(),request.user,user=request.user).order_by('-updated_at')
        agent_labels=dict(get_agent_choices())
        items_by_group={key:[] for key,_ in SIDEBAR_GROUPS}
        for conversation in conversations:
            title=conversation.title
            if title == 'New conversation':
                first=conversation.messages.filter(role='user').order_by('id').first()
                title=first.content[:50] if first and first.content else 'Untitled chat'
            items_by_group[_sidebar_group_key(conversation.updated_at)].append({
                'session_id':conversation.session_id,
                'agent_type':conversation.agent_type,
                'title':title,
                'agent_label':agent_labels.get(conversation.agent_type,conversation.agent_type),
            })
        sidebar_groups=[
            {'key':key,'label':label,'items':items_by_group[key]}
            for key,label in SIDEBAR_GROUPS if items_by_group[key]
        ]
        context={
            **admin.site.each_context(request),
            'title':'Chat',
            'sidebar_groups':sidebar_groups,
            'agent_choices':get_agent_choices(),
            'selected_agent':agent_type or '',
        }
        return render(request,'chat/chat_page.html',context)



class SendMessageView(View):
    def post(self, request):
        if request.content_type == 'application/json':
            payload = json.loads(request.body or '{}')
        else:
            payload = request.POST

        text=payload.get('message', '')
        session_id=payload.get('session_id') or None
        uploaded_file=request.FILES.get('file')

        # A file sent with no text is stored with empty text (the page shows the file as a
        # card); the chat is titled after the file and the AI gets a sensible default question.
        title_source=text or (uploaded_file.name if uploaded_file else '')
        question=text
        if not text and uploaded_file:
            question=(
                f"I've attached {uploaded_file.name}. Tell me what it contains (columns and number "
                "of rows) and suggest a few useful analyses or charts."
            )

        if session_id:
            conversation=get_conversation_by_session_id(session_id)
        else:
            agent_type=payload.get('agent_type') or 'support'
            if not is_valid_agent_type(agent_type):
                agent_type='support'
            conversation=Conversation.objects.create(user=request.user,title=title_source[:50],company=request.user.current_company,agent_type=agent_type)
        if conversation.title == 'New conversation':
            conversation.title = title_source[:50]
            conversation.save(update_fields=['title'])
        if uploaded_file and uploaded_file.name.lower().endswith('.pdf') and not text:
            # A PDF attached in chat stays a chat attachment (not a Document) until the user asks to save it.
            question=(
                f"I've attached {uploaded_file.name}. Tell me what it contains and "
                "suggest a few useful analyses or charts."
            )
        user_message=Message.objects.create(conversation=conversation,content=text,role='user',file=uploaded_file,session_id=conversation.session_id,user=conversation.user,company=conversation.company)
        file_paths=conversation_file_paths(conversation, user_message)
        # 'process' / 'save' typed with an attachment are chat commands, answered without the agent.
        reply = (handle_command(conversation, text) if text else None) or generate_reply(conversation, question, request.user.current_company, file_paths=file_paths)
        assistant_message = Message.objects.create(conversation=conversation, content=reply, role='assistant',session_id=conversation.session_id,user=conversation.user,company=conversation.company)

        conversation.summary = update_summary(conversation, question, reply)
        conversation.save(update_fields=['summary'])



        return JsonResponse({'reply':reply,'session_id':conversation.session_id,'agent_type':conversation.agent_type,'title':conversation.title,'file_url':_file_url(user_message)})


ALLOWED_UPLOAD_EXTENSIONS = ('.pdf', '.csv')
MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def _file_url(message):
    """Company-protected link for a message's file; both name and link come from Message.file."""
    return reverse('chat:message-file', args=[message.id]) if message.file else None


def _check_upload(uploaded):
    """Error text if the upload is not an allowed .pdf/.csv within the size limit, else ''."""
    if not uploaded.name.lower().endswith(ALLOWED_UPLOAD_EXTENSIONS):
        return 'Only .pdf and .csv files can be uploaded'
    if uploaded.size > MAX_UPLOAD_BYTES:
        return 'File is too large (100 MB max)'
    return ''


class MessageFileView(LoginRequiredMixin, View):
    """GET /chat/files/<message_id>/ : the uploaded file, for users of the same company only."""

    def get(self, request, message_id):
        message = scope_queryset(Message.objects.exclude(file='').exclude(file__isnull=True), request.user).filter(pk=message_id).first()
        if not message or not message.file.storage.exists(message.file.name):
            raise Http404('File not found')
        return FileResponse(message.file.open('rb'), as_attachment=False, filename=file_display_name(message.file.name))


class FileUploadView(LoginRequiredMixin, View):
    """POST /chat/api/files/ (multipart: file, optional session_id, agent_type).
    Stores the PDF/CSV on a conversation and returns its link; the agent can then chart, process or save it."""

    def post(self, request):
        uploaded = request.FILES.get('file')
        if not uploaded:
            return JsonResponse({'error': 'file is required'}, status=400)
        error = _check_upload(uploaded)
        if error:
            return JsonResponse({'error': error}, status=400)
        session_id = request.POST.get('session_id')
        if session_id:
            try:
                conversation = scope_queryset(Conversation.objects.all(), request.user, user=request.user).get(session_id=session_id)
            except (Conversation.DoesNotExist, ValidationError, ValueError):
                return JsonResponse({'error': 'Conversation not found'}, status=404)
        else:
            agent_type = request.POST.get('agent_type') or 'support'
            if not is_valid_agent_type(agent_type):
                return JsonResponse({'error': 'Unknown agent'}, status=404)
            conversation = Conversation.objects.create(
                user=request.user, title=uploaded.name[:50], company=request.user.current_company, agent_type=agent_type,
            )
        message = Message.objects.create(conversation=conversation, content='', role='user', file=uploaded, session_id=conversation.session_id, user=conversation.user, company=conversation.company)
        return JsonResponse({
            'file_name': file_display_name(message.file.name),
            'file_url': _file_url(message),
            'session_id': conversation.session_id,
            'message_id': message.id,
        }, status=201)


class AgentCallView(LoginRequiredMixin, View):
    """POST /chat/api/agents/<agent_type>/call/  {"message": "...", "session_id": "<optional>", "file_url": "<optional>"}
    (JSON, or multipart with an uploaded `file` instead of file_url.) Sends one message to that agent and returns its reply."""

    def post(self, request, agent_type):
        if not is_valid_agent_type(agent_type):
            return JsonResponse({'error': 'Unknown agent'}, status=404)
        if request.content_type == 'application/json':
            try:
                payload = json.loads(request.body or '{}')
            except ValueError:
                return JsonResponse({'error': 'Invalid JSON'}, status=400)
        else:
            payload = request.POST
        text = (payload.get('message') or '').strip()
        if not text:
            return JsonResponse({'error': 'message is required'}, status=400)

        uploaded = request.FILES.get('file')
        if uploaded:
            error = _check_upload(uploaded)
            if error:
                return JsonResponse({'error': error}, status=400)
        source = None
        file_url = (payload.get('file_url') or '').strip()
        if file_url:
            match = re.search(r'/chat/files/(\d+)/?$', file_url)
            source = match and scope_queryset(Message.objects.exclude(file='').exclude(file__isnull=True), request.user).filter(pk=match.group(1)).first()
            if not source:
                return JsonResponse({'error': 'file_url not found'}, status=404)

        session_id = payload.get('session_id')
        if session_id:
            try:
                conversation = scope_queryset(Conversation.objects.all(), request.user, user=request.user).get(session_id=session_id)
            except (Conversation.DoesNotExist, ValidationError, ValueError):
                return JsonResponse({'error': 'Conversation not found'}, status=404)
            if conversation.agent_type != agent_type:
                return JsonResponse({'error': 'This conversation belongs to a different agent'}, status=400)
        else:
            conversation = Conversation.objects.create(
                user=request.user, title=text[:50], company=request.user.current_company, agent_type=agent_type,
            )

        # An uploaded file, or an earlier file_url, is attached to this message so the agent's tools can use it.
        user_message = Message.objects.create(conversation=conversation, content=text, role='user', file=uploaded or (source.file.name if source else None), session_id=conversation.session_id, user=conversation.user, company=conversation.company)
        reply = handle_command(conversation, text) or generate_reply(conversation, text, request.user.current_company, file_paths=conversation_file_paths(conversation, user_message))
        Message.objects.create(conversation=conversation, content=reply, role='assistant', session_id=conversation.session_id, user=conversation.user, company=conversation.company)
        conversation.summary = update_summary(conversation, text, reply)
        conversation.save(update_fields=['summary'])
        return JsonResponse({'reply': reply, 'session_id': conversation.session_id, 'agent_type': conversation.agent_type, 'file_url': _file_url(user_message)})


class NewConversationView(LoginRequiredMixin, View):
    def post(self, request, agent_type=None):
        payload = json.loads(request.body or '{}')
        agent_type = agent_type or payload.get('agent_type') or 'support'
        if not is_valid_agent_type(agent_type):
            agent_type = 'support'
        conversation = Conversation.objects.create(
            user=request.user,
            title='New conversation',
            company=request.user.current_company,
            agent_type=agent_type,
        )
        return JsonResponse({'session_id': conversation.session_id, 'agent_type': conversation.agent_type})


class OrderStatusView(View):
    def get(self, request):
        order_number = request.GET.get('order_id')
        if not order_number:
            return JsonResponse({'error': 'order_id is required'}, status=400)
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            return JsonResponse({'error': f'No order found with ID {order_number}'}, status=404)
        return JsonResponse({
            'order_number': order.order_number,
            'customer_name': order.customer_name,
            'status': order.get_status_display(),
        })


class CustomerOrdersView(View):
    def get(self, request):
        customer_name = request.GET.get('customer_name')
        if not customer_name:
            return JsonResponse({'error': 'customer_name is required'}, status=400)
        orders = Order.objects.filter(customer_name__iexact=customer_name)
        return JsonResponse({
            'orders': [
                {'order_number': o.order_number, 'status': o.get_status_display()}
                for o in orders
            ]
        })


class DocumentNotificationsView(LoginRequiredMixin, View):
    def get(self, request):
        since = int(request.GET.get('since') or 0)
        qs = Message.objects.filter(
            user=request.user,
            role='assistant',
            conversation__title='Document processing updates',
        )
        latest = qs.order_by('-id').first()
        latest_id = latest.id if latest else 0
        new_messages = qs.filter(id__gt=since).order_by('id') if since else Message.objects.none()
        return JsonResponse({
            'latest_id': latest_id,
            'messages': [{'id': m.id, 'content': m.content} for m in new_messages],
        })


@method_decorator(csrf_exempt, name='dispatch')
class TemporalAuthView(View):
    """Called by the Temporal UI login service (nginx/auth), never by browsers. With a password it
    checks the credentials; without one it only checks the user is still active (session re-check).
    Guarded by a shared-secret header; any active Django user is accepted."""
    def post(self, request):
        secret = settings.TEMPORAL_AUTH_DJANGO_SECRET
        sent = request.headers.get('X-Temporal-Auth-Secret', '')
        if not secret or not hmac.compare_digest(sent, secret):
            return JsonResponse({'ok': False}, status=403)
        try:
            payload = json.loads(request.body or '{}')
        except ValueError:
            return JsonResponse({'ok': False}, status=400)
        username = payload.get('username') or ''
        password = payload.get('password')
        if password is None:
            ok = get_user_model().objects.filter(**{get_user_model().USERNAME_FIELD: username}, is_active=True).exists()
        else:
            ok = authenticate(request, username=username, password=password) is not None
        return JsonResponse({'ok': ok})


VIA_LABELS = {'direct': 'Direct', 'celery': 'Celery', 'celery_priority': 'Celery priority', 'kafka': 'Kafka',
              'temporal': 'Temporal', 'temporal_extract': 'Temporal (text only)'}


def _document_info(document):
    """What the chat card's tables and Start/Stop button need to know about a document."""
    return {
        'id': document.pk,
        'status': document.get_status_display(),
        'via': VIA_LABELS.get(document.processed_via, '-'),
        'chunks': document.chunks.count(),
        'can_start': can_start(document),
        'can_stop': can_stop(document),
    }


class DocumentListView(LoginRequiredMixin, View):
    """Rows for the chat's documents card. Own company only; `ids=1,2,3` narrows it to what a chat answer listed."""
    def get(self, request):
        documents = Document.objects.filter(company=request.user.current_company_id)
        ids = [int(i) for i in re.findall(r'\d+', request.GET.get('ids', ''))][:100]
        if request.GET.get('ids') is not None:
            documents = documents.filter(pk__in=ids)
        documents = documents.annotate(chunk_count=Count('chunks')).order_by('-id')[:100]
        return JsonResponse({'documents': [{
            'id': d.pk,
            'name': file_display_name(d.file.name) if d.file else f'Document {d.pk}',
            'status': d.status,
            'via': VIA_LABELS.get(d.processed_via, '-'),
            'chunks': d.chunk_count,
            'finished': d.updated_at.isoformat() if d.status in ('processed', 'error') and d.updated_at else '',
            'can_start': can_start(d),
            'can_stop': can_stop(d),
        } for d in documents]})


class DocumentStartStopView(LoginRequiredMixin, View):
    """POST start/stop for one document of the user's own company (superusers included)."""
    action = None

    def post(self, request, doc_id):
        document = Document.objects.filter(pk=doc_id, company=request.user.current_company_id).first()
        if not document:
            return JsonResponse({'ok': False, 'message': 'Document not found.'}, status=404)
        ok, message = (start_document if self.action == 'start' else stop_document)(document)
        return JsonResponse({'ok': ok, 'message': message}, status=200 if ok else 409)


class DocumentRunStatusView(LoginRequiredMixin, View):
    """Same run data as the admin dialog, for the live card in the chat."""
    def get(self, request, doc_id):
        document = scope_queryset(Document.objects.filter(pk=doc_id), request.user).first()
        if not document:
            return JsonResponse({'error': 'Document not found.'}, status=404)
        try:
            run = get_run_status(doc_id)
        except Exception:
            return JsonResponse({'error': 'Temporal is unreachable.'}, status=502)
        return JsonResponse({
            'document_status': document.status,
            'chunks': document.chunks.count(),
            'document': _document_info(document),
            'run': run,
        })


def _process_intro(request, workflow_id):
    """The assistant message that announced this temporary run, if it is the current user's own."""
    return Message.objects.filter(
        conversation__user=request.user, role='assistant', content__startswith='Processing', content__contains=workflow_id,
    ).select_related('conversation').first()


class ProcessRunStatusView(LoginRequiredMixin, View):
    """Run data for the live card of a chat 'process' (temporary Temporal run, no Document)."""
    FINAL_STATUS = {'Completed': 'processed', 'Running': 'started', 'ContinuedAsNew': 'started'}

    def get(self, request, workflow_id):
        # Only runs that this user's own chat reported can be looked up.
        if not _process_intro(request, workflow_id):
            return JsonResponse({'error': 'Run not found.'}, status=404)
        try:
            run = get_extract_run_status(workflow_id)
        except Exception:
            return JsonResponse({'error': 'Temporal is unreachable.'}, status=502)
        if run is None:
            return JsonResponse({'error': 'Run not found.'}, status=404)
        return JsonResponse({
            'document_status': self.FINAL_STATUS.get(run['status'], 'error'),
            'chunks': 0,
            'kind': 'extract',
            'can_stop': run['status'] == 'Running',
            'run': run,
        })


class ProcessRunStopView(LoginRequiredMixin, View):
    """Cancel a running temporary 'process' run (same code as the stop_process_run agent tool)."""
    def post(self, request, workflow_id):
        ok, message, status = process_runs.stop_run(request.user, workflow_id)
        return JsonResponse({'ok': ok, 'message': message}, status=status)


class ProcessRunRestartView(LoginRequiredMixin, View):
    """Run a stopped/failed temporary 'process' run again: a new run and a new live card in the same chat
    (same code as the restart_process_run agent tool)."""
    def post(self, request, workflow_id):
        ok, text, status = process_runs.restart_run(request.user, workflow_id)
        return JsonResponse({'ok': True, 'content': text} if ok else {'ok': False, 'message': text}, status=status)


class ProcessRunSummaryView(LoginRequiredMixin, View):
    """Once a temporary 'process' run has finished, post its summary into the chat (once)."""
    def post(self, request, workflow_id):
        intro = _process_intro(request, workflow_id)
        if not intro:
            return JsonResponse({'error': 'Run not found.'}, status=404)
        existing = Message.objects.filter(
            conversation=intro.conversation, role='assistant', content__startswith='Summary of',
            content__contains=f'workflow id {workflow_id}',
        ).first()
        if existing:
            return JsonResponse({'content': existing.content, 'existing': True})
        try:
            text = (get_extract_text(workflow_id) or '').strip()
        except Exception:
            return JsonResponse({'error': 'The run has not finished successfully.'}, status=409)
        match = re.search(r"Processing '(.*?)' with Temporal", intro.content)
        name = match.group(1) if match else 'the PDF'
        if not text:
            content = f"Summary of '{name}' (workflow id {workflow_id}): no text was found in the PDF."
        else:
            from chat.service.commands import summarize_text
            content = f"Summary of '{name}' (workflow id {workflow_id}):\n{summarize_text(name, text)}"
        Message.objects.create(
            conversation=intro.conversation, content=content, role='assistant',
            session_id=intro.conversation.session_id, user=request.user, company=intro.conversation.company,
        )
        return JsonResponse({'content': content, 'existing': False})


class DocumentSummaryView(LoginRequiredMixin, View):
    """Once the document's run is final, post the run summary as a bot message in the chat it was uploaded from."""
    def post(self, request, doc_id):
        document = scope_queryset(Document.objects.filter(pk=doc_id), request.user).first()
        try:
            conversation = Conversation.objects.filter(session_id=request.POST.get('session_id'), user=request.user).first()
        except ValidationError:
            conversation = None
        if not document or conversation is None:
            return JsonResponse({'error': 'Document or chat not found.'}, status=404)
        if document.status not in ('processed', 'error'):
            return JsonResponse({'error': 'The document is still being processed.'}, status=409)
        outcome = 'has finished processing and is ready to use' if document.status == 'processed' else 'failed to process'
        text = f"Document #{document.pk} ({file_display_name(document.file.name)}) {outcome}."
        try:
            run = get_run_status(doc_id)
        except Exception:
            run = None
        if run:
            text += '\n\n' + summarize_run(run, document.chunks.count())
        Message.objects.create(
            conversation=conversation, content=text, role='assistant',
            session_id=conversation.session_id, user=request.user, company=conversation.company,
        )
        return JsonResponse({'content': text})


class ConversationMessagesView(View):
    def get(self, request, session_id):
        conversation=get_conversation_by_session_id(session_id)
        messages=Message.objects.filter(conversation=conversation).order_by('id')
        data=[]
        for msg in messages:
            item={'sender':'bot' if msg.role == 'assistant' else 'user', 'content':msg.content}
            if msg.file:
                file_name=file_display_name(msg.file.name)
                item['file_name']=file_name
                item['file_url']=_file_url(msg)
                # A file sent with no text is saved with its name as the text; the chip already shows it.
                if _name_key(msg.content) == _name_key(file_name):
                    item['content']=''
            data.append(item)
        return JsonResponse({'messages':data,'agent_type':conversation.agent_type})


class AgentsUIPageView(LoginRequiredMixin, View):
    def get(self, request):
        context={
            **admin.site.each_context(request),
            'title':'Workflows',
        }
        return render(request, 'chat/agents_ui.html', context)


def _agent_to_dict(agent):
    return {
        'id': agent.id,
        'agent_type': agent.agent_type,
        'label': agent.label,
        'description': agent.description,
        'prompt': agent.prompt,
        'workflow_json': agent.workflow_json or {},
        'is_active': agent.is_active,
        'tools': [{'id': t.id, 'name': t.name} for t in agent.tools.all()],
        'linked_agents': [{'id': a.id, 'label': a.label} for a in agent.linked_agents.all()],
    }


def _set_linked_agents(agent, linked_agent_ids):
    """Replace agent's sub-agents. Returns an error message, or None when saved."""
    children = Agent.objects.filter(id__in=linked_agent_ids or [])
    child_ids = list(children.values_list('id', flat=True))
    if agent.delegation_cycle(child_ids):
        return 'An agent cannot be linked to itself or form a loop with its sub-agents.'
    agent.linked_agents.set(child_ids)
    return None


def _tool_to_dict(tool):
    return {
        'id': tool.id,
        'name': tool.name,
        'description': tool.description,
        'args_schema': tool.args_schema,
        'endpoint_url': tool.endpoint_url,
        'http_method': tool.http_method,
        'workflow_json': tool.workflow_json or {},
        'is_active': tool.is_active,
        'agents': [{'id': a.id, 'label': a.label} for a in tool.agents.all()],
    }


def _company_for(request):
    return None if is_admin(request.user) else request.user.current_company


class AgentListCreateView(LoginRequiredMixin, View):
    def get(self, request):
        agents = Agent.objects.all()
        company = _company_for(request)
        if company is not None:
            agents = agents.filter(company=company)
        return JsonResponse({
            'agents': [_agent_to_dict(a) for a in agents],
            'http_method_choices': HTTP_METHOD_CHOICES,
        })

    def post(self, request):
        payload = json.loads(request.body or '{}')
        label = (payload.get('label') or '').strip()
        agent_type = (payload.get('agent_type') or '').strip()
        if not label or not agent_type:
            return JsonResponse({'error': 'label and agent_type are required'}, status=400)
        company = request.user.current_company
        agent = Agent.objects.create(
            company=company,
            agent_type=agent_type,
            label=label,
            description=payload.get('description', ''),
            prompt=payload.get('prompt', ''),
            workflow_json=payload.get('workflow_json') or {},
            created_by=request.user,
            updated_by=request.user,
        )
        tool_ids = payload.get('tool_ids') or []
        if tool_ids:
            agent.tools.set(ToolDefinition.objects.filter(id__in=tool_ids, company=company))
        error = _set_linked_agents(agent, payload.get('linked_agent_ids'))
        if error:
            return JsonResponse({'error': error}, status=400)
        return JsonResponse(_agent_to_dict(agent), status=201)


class AgentDetailView(LoginRequiredMixin, View):
    def _get_agent(self, request, pk):
        agents = Agent.objects.all()
        company = _company_for(request)
        if company is not None:
            agents = agents.filter(company=company)
        return agents.filter(pk=pk).first()

    def get(self, request, pk):
        agent = self._get_agent(request, pk)
        if not agent:
            return JsonResponse({'error': 'Not found'}, status=404)
        return JsonResponse(_agent_to_dict(agent))

    def put(self, request, pk):
        agent = self._get_agent(request, pk)
        if not agent:
            return JsonResponse({'error': 'Not found'}, status=404)
        payload = json.loads(request.body or '{}')
        if 'linked_agent_ids' in payload:
            error = _set_linked_agents(agent, payload['linked_agent_ids'])
            if error:
                return JsonResponse({'error': error}, status=400)
        for field in ('label', 'agent_type', 'description', 'prompt'):
            if field in payload:
                setattr(agent, field, payload[field])
        if 'workflow_json' in payload:
            agent.workflow_json = payload['workflow_json'] or {}
        if 'is_active' in payload:
            agent.is_active = bool(payload['is_active'])
        agent.updated_by = request.user
        agent.save()
        if 'tool_ids' in payload:
            agent.tools.set(ToolDefinition.objects.filter(id__in=payload['tool_ids'] or [], company=agent.company))
        return JsonResponse(_agent_to_dict(agent))

    def delete(self, request, pk):
        agent = self._get_agent(request, pk)
        if not agent:
            return JsonResponse({'error': 'Not found'}, status=404)
        agent.delete()
        return JsonResponse({'deleted': True})


class ToolListCreateView(LoginRequiredMixin, View):
    def get(self, request):
        tools = ToolDefinition.objects.all()
        company = _company_for(request)
        if company is not None:
            tools = tools.filter(company=company)
        return JsonResponse({'tools': [_tool_to_dict(t) for t in tools]})

    def post(self, request):
        payload = json.loads(request.body or '{}')
        name = (payload.get('name') or '').strip()
        endpoint_url = (payload.get('endpoint_url') or '').strip()
        if not name or not endpoint_url:
            return JsonResponse({'error': 'name and endpoint_url are required'}, status=400)
        agent_ids = payload.get('agent_ids') or []
        company = request.user.current_company
        if agent_ids and is_admin(request.user):
            # Staff see agents of every company: create the tool in the agent's own company so the link sticks.
            first_agent = Agent.objects.filter(id__in=agent_ids).first()
            if first_agent:
                company = first_agent.company
        tool = ToolDefinition.objects.create(
            company=company,
            name=name,
            description=payload.get('description', ''),
            args_schema=payload.get('args_schema') or [],
            endpoint_url=endpoint_url,
            http_method=payload.get('http_method', 'POST'),
            workflow_json=payload.get('workflow_json') or {},
            created_by=request.user,
            updated_by=request.user,
        )
        if agent_ids:
            tool.agents.set(Agent.objects.filter(id__in=agent_ids, company=company))
        return JsonResponse(_tool_to_dict(tool), status=201)


class ToolDetailView(LoginRequiredMixin, View):
    def _get_tool(self, request, pk):
        tools = ToolDefinition.objects.all()
        company = _company_for(request)
        if company is not None:
            tools = tools.filter(company=company)
        return tools.filter(pk=pk).first()

    def get(self, request, pk):
        tool = self._get_tool(request, pk)
        if not tool:
            return JsonResponse({'error': 'Not found'}, status=404)
        return JsonResponse(_tool_to_dict(tool))

    def put(self, request, pk):
        tool = self._get_tool(request, pk)
        if not tool:
            return JsonResponse({'error': 'Not found'}, status=404)
        payload = json.loads(request.body or '{}')
        for field in ('name', 'description', 'endpoint_url', 'http_method'):
            if field in payload:
                setattr(tool, field, payload[field])
        if 'args_schema' in payload:
            tool.args_schema = payload['args_schema'] or []
        if 'workflow_json' in payload:
            tool.workflow_json = payload['workflow_json'] or {}
        if 'is_active' in payload:
            tool.is_active = bool(payload['is_active'])
        tool.updated_by = request.user
        tool.save()
        if 'agent_ids' in payload:
            tool.agents.set(Agent.objects.filter(id__in=payload['agent_ids'] or [], company=tool.company))
        return JsonResponse(_tool_to_dict(tool))

    def delete(self, request, pk):
        tool = self._get_tool(request, pk)
        if not tool:
            return JsonResponse({'error': 'Not found'}, status=404)
        tool.delete()
        return JsonResponse({'deleted': True})


# class AgentGraphView(View):
#     def get(self, request, agent_type):
#         if agent_type not in AGENTS:
#             raise Http404('Unknown agent type')
#         graph = get_agent_graph(agent_type)
#         mermaid = graph.get_graph().draw_mermaid()
#         return render(request, 'chat/agent_graph.html', {
#             'agent_type': agent_type,
#             'label': AGENTS[agent_type]['label'],
#             'description': AGENTS[agent_type]['description'],
#             'mermaid': mermaid,
#         })

