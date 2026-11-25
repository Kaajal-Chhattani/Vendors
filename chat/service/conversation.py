import os
import re
from functools import cached_property

from pypdf import PdfReader

from chat.models import Conversation, Message
from chat.service.ingest import document_csv_path


def get_conversation_by_session_id(session_id):
    return Conversation.objects.get(session_id=session_id)


def file_display_name(path):
    """Stored name -> the name the user uploaded (drops Django's '_AbC12xY' de-dup suffix)."""
    return re.sub(r"_[A-Za-z0-9]{7}(?=\.(?:csv|pdf)$)", "", os.path.basename(path), flags=re.IGNORECASE)


def conversation_file_paths(conversation, user_message=None):
    """Paths of every file uploaded in this conversation, newest first, so the
    agent can use a CSV attached in an earlier message. Files that no longer
    exist on disk are skipped. Empty list if there are none."""
    uploads = (
        Message.objects.filter(conversation=conversation, role='user')
        .exclude(file='')
        .exclude(file__isnull=True)
        .order_by('-id')
    )
    messages = list(uploads)
    if user_message is not None and user_message.file and user_message.id not in {m.id for m in messages}:
        messages.insert(0, user_message)
    paths = []
    for message in messages:
        path = message.file.path
        if path not in paths and path.lower().endswith('.csv') and os.path.exists(path):
            paths.append(path)
    return paths


def conversation_documents(conversation):
    """Documents uploaded through the chat's 'Upload document' button in this conversation, newest first."""
    seen = {}
    for message in conversation.messages.filter(document__isnull=False).select_related("document").order_by("-id"):
        seen.setdefault(message.document_id, message.document)
    return list(seen.values())


class PendingPdf:
    """A PDF uploaded in chat that has not been saved as a Document yet. It exposes the same
    pk / file / raw_text a Document does, so the chart and read tools treat both alike."""

    def __init__(self, message):
        self.message = message
        self.file = message.file
        self.pk = f"msg{message.pk}"

    @cached_property
    def raw_text(self):
        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(self.file.path).pages)
        except Exception:
            return ""


def conversation_pdfs(conversation):
    """Saved Documents and still-unsaved PDFs uploaded in this conversation, newest first."""
    seen = set()
    pdfs = []
    for message in conversation.messages.filter(role="user").select_related("document").order_by("-id"):
        if message.document_id:
            if message.document_id not in seen and message.document.file:
                seen.add(message.document_id)
                pdfs.append(message.document)
        elif message.file and message.file.name.lower().endswith(".pdf") and os.path.exists(message.file.path):
            pdfs.append(PendingPdf(message))
    return pdfs


def document_csv_paths(conversation):
    """Cached CSVs already made from this conversation's PDFs (see ingest.ensure_document_csv)."""
    return [p for p in (document_csv_path(d) for d in conversation_pdfs(conversation)) if os.path.exists(p)]
