from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from chat.models import Conversation, Message

UPDATES_TITLE = 'Document processing updates'


def notify_document_processed(document):
    """Post a chat message telling the document's creator it finished (or failed)."""
    user_id = document.created_by_id
    if not user_id:
        return None

    if document.status == 'processed':
        text = f"Document #{document.pk} has finished processing and is ready to use."
    else:
        text = f"Document #{document.pk} failed to process. Please check it and try again."

    # Always use the dedicated updates conversation; DocumentNotificationsView reads from it.
    conversation = Conversation.objects.filter(
        user_id=user_id,
        company=document.company,
        title=UPDATES_TITLE,
    ).order_by('-id').first()
    if conversation is None:
        conversation = Conversation.objects.create(
            user_id=user_id,
            company=document.company,
            title=UPDATES_TITLE,
        )

    Message.objects.create(
        conversation=conversation,
        content=text,
        role='assistant',
        session_id=conversation.session_id,
        user_id=user_id,
        company=conversation.company,
    )

    async_to_sync(get_channel_layer().group_send)(
        f'chat_{conversation.session_id}',
        {
            'type': 'chat.message',
            'sender': 'bot',
            'content': text,
        },
    )
    return conversation
