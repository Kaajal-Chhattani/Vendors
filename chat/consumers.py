import logging

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer

from auth.permissions import is_admin
from chat.models import Conversation, Message
from chat.service.commands import handle_command
from chat.service.conversation import conversation_file_paths, file_display_name
from chat.service.llm import generate_reply
from chat.service.summary import update_summary

logger = logging.getLogger(__name__)


class ChatConsumer(JsonWebsocketConsumer):
    def connect(self):
        user = self.scope['user']
        session_id = self.scope['url_route']['kwargs']['session_id']

        if not user.is_authenticated:
            self.close()
            return

        try:
            conversation = Conversation.objects.get(session_id=session_id)
        except Conversation.DoesNotExist:
            self.close()
            return

        if not is_admin(user) and (
            conversation.user_id != user.id or conversation.company_id != user.current_company_id
        ):
            self.close()
            return

        self.conversation = conversation
        self.group_name = f'chat_{session_id}'
        async_to_sync(self.channel_layer.group_add)(self.group_name, self.channel_name)
        self.accept()

    def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            async_to_sync(self.channel_layer.group_discard)(self.group_name, self.channel_name)

    def receive_json(self, content, **kwargs):
        text = content.get('message', '')
        if not text:
            return

        conversation = self.conversation
        user = self.scope['user']

        if conversation.title == 'New conversation':
            conversation.title = text[:50]
            conversation.save(update_fields=['title'])

        Message.objects.create(
            conversation=conversation,
            content=text,
            role='user',
            session_id=conversation.session_id,
            user=user,
            company=conversation.company,
        )
        # The page shows the user's own message immediately, so it is not echoed back here.

        try:
            file_paths = conversation_file_paths(conversation)
            saved_before = self._saved_document_ids()
            # 'process' / 'save' for uploaded PDFs are answered here, without the agent.
            reply = handle_command(conversation, text) or generate_reply(conversation, text, conversation.company, file_paths=file_paths)
        except Exception:
            logger.exception('Failed to generate reply for conversation %s', conversation.pk)
            async_to_sync(self.channel_layer.group_send)(
                self.group_name,
                {
                    'type': 'chat.message',
                    'sender': 'bot',
                    'content': 'Sorry, the assistant is unavailable right now. Please try again later.',
                },
            )
            return

        assistant_message = Message.objects.create(
            conversation=conversation,
            content=reply,
            role='assistant',
            session_id=conversation.session_id,
            user=user,
            company=conversation.company,
        )
        conversation.summary = update_summary(conversation, text, reply)
        conversation.save(update_fields=['summary'])
        # A PDF saved by this reply (save_document) gets a live Temporal run card on the page.
        new_ids = self._saved_document_ids() - saved_before
        saved = Message.objects.filter(conversation=conversation, document_id__in=new_ids).select_related('document').first() if new_ids else None
        self._broadcast(assistant_message, agent_type=conversation.agent_type, saved=saved)

    def _saved_document_ids(self):
        return set(Message.objects.filter(conversation=self.conversation, document__isnull=False).values_list('document_id', flat=True))

    def _broadcast(self, message, agent_type=None, saved=None):
        async_to_sync(self.channel_layer.group_send)(
            self.group_name,
            {
                'type': 'chat.message',
                'sender': 'bot' if message.role == 'assistant' else 'user',
                'content': message.content,
                'agent_type': agent_type,
                'document_id': saved.document_id if saved else None,
                'document_name': file_display_name(saved.document.file.name) if saved else None,
            },
        )

    def chat_message(self, event):
        self.send_json({
            'sender': event['sender'],
            'content': event['content'],
            'agent_type': event.get('agent_type'),
            'document_id': event.get('document_id'),
            'document_name': event.get('document_name'),
        })
