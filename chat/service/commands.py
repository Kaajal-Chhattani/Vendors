"""Chat commands 'process' and 'save' for PDFs uploaded in a conversation.

process -> start a temporary Temporal run (extract text, split into chunks, embed the chunks and
           discard them) and answer at once with a live run card; nothing is saved. When the run
           finishes the page asks for the summary (ProcessRunSummaryView), which is posted as a
           message so later turns (and charts) can use it.
save    -> ask which method to use (Celery / Temporal / Kafka), then store a rag.Document
           and process it with that method; a PDF already processed in chat reuses its row.
"""
import json
import logging
import re

import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from chat.models import Message
from chat.service.conversation import PendingPdf, conversation_pdfs, file_display_name
from chat.service.llm import call_deepseek
from chat.service.documents import UrlFetchError, fetch_url_text, register_pdf_for_processing, register_url_for_processing, start_processing
from rag.models import Document
from rag.service.cron_management import DocumentProcessor
from rag.temporal.client import start_pdf_extract

logger = logging.getLogger(__name__)

MAX_COMMAND_WORDS = 6  # longer messages ("how do I process refunds and ...") go to the agent
MAX_SUMMARY_INPUT_CHARS = 20000  # how much of the text the summary is made from
SAVE_METHOD_QUESTION = "Which method should I use to save it: **Celery**, **Temporal** or **Kafka**?"

_COMMAND = re.compile(r"^\W*(process|save)\b", re.IGNORECASE)
# Natural phrasings ("can you process this document in temporal") count as commands only while a
# PDF is waiting, the message is short, names the file ("this/it/document/pdf/file") and isn't a question.
MAX_NATURAL_WORDS = 14
_VERB = re.compile(r"\b(process|save)\b", re.IGNORECASE)
_TARGET = re.compile(r"\b(this|it|document|pdf|file|upload\w*)\b", re.IGNORECASE)
_QUESTION = re.compile(r"^\W*(how|what|why|when|where|which|who|does|is|are|do)\b", re.IGNORECASE)
_METHOD = re.compile(r"\b(celery|temporal|kafka)\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


EXTRACT_VIA = "temporal_extract"


def _is_extract_only(pdf):
    return isinstance(pdf, Document) and pdf.processed_via == EXTRACT_VIA


def _documents_card(document_id):
    """A ```documents block: the chat page shows it as the tabbed table with Start / Stop / Retry buttons."""
    return "\n\n```documents\n" + json.dumps({"ids": [document_id]}) + "\n```"


def _newest_pending_pdf(conversation):
    """Newest PDF that can still be processed/saved: an unsaved upload, or one only text-extracted by 'process'."""
    return next((d for d in conversation_pdfs(conversation) if isinstance(d, PendingPdf) or _is_extract_only(d)), None)


def _last_assistant_message(conversation):
    return conversation.messages.filter(role="assistant").order_by("-id").first()


def _is_awaiting_save_method(conversation):
    last = _last_assistant_message(conversation)
    return bool(last and SAVE_METHOD_QUESTION in last.content)


def _processed_marker(name):
    return f"Processing '{name}' with Temporal"


def _process_card(workflow_id, name):
    """A ```processrun block: the chat page shows it as the live task card for the temporary run."""
    return "\n\n```processrun\n" + json.dumps({"id": workflow_id, "name": name}) + "\n```"


def _process(conversation, pdf):
    name = file_display_name(pdf.file.name)
    if isinstance(pdf, Document):
        return f"'{name}' was already processed as document #{pdf.pk}. Say **save** to chunk and embed it."
    try:
        workflow_id = start_pdf_extract(pdf.file.path)
    except Exception:
        logger.exception("Temporal could not start processing %s", name)
        return f"Could not process '{name}': Temporal could not be reached."
    return (
        f"{_processed_marker(name)} (workflow id {workflow_id}). Nothing is saved to your documents: "
        f"say **save** (and which method: Celery, Temporal or Kafka) to keep it. "
        f"The summary follows when the run finishes."
        f"{_process_card(workflow_id, name)}"
    )


def summarize_text(name, text):
    return _summarize(name, text)


def _summarize(name, text):
    """A short summary of the extracted text; it becomes the context kept in the chat message."""
    prompt = (
        f"Summarize this document ('{name}') in 4-6 short bullet points: what it is, the main columns or "
        "sections, key totals and figures (copy numbers exactly), and anything notable. Reply with "
        f"only the bullets.\n\n{text[:MAX_SUMMARY_INPUT_CHARS]}"
    )
    try:
        return call_deepseek([{"role": "user", "content": prompt}])["content"].strip()
    except Exception:
        logger.exception("Could not summarize %s", name)
        return f"(No summary available; {len(text)} characters of text were extracted.)"


def _save(conversation, pdf, method):
    name = file_display_name(pdf.file.name)
    if isinstance(pdf, Document):
        error = start_processing(pdf, method)
        message = f"'{name}' was {error}." if error else f"Started processing document #{pdf.pk} ('{name}') with {method.title()}."
        return message + _documents_card(pdf.pk)
    with pdf.file.open("rb") as handle:
        content = ContentFile(handle.read(), name=name)
    document, error = register_pdf_for_processing(content, conversation.user, method=method)
    if document is None:
        return f"Could not save '{name}': {error}."
    pdf.message.document = document
    pdf.message.save(update_fields=["document"])
    if error:
        return f"'{name}' was {error}." + _documents_card(document.pk)
    return f"Saved '{name}' as document #{document.pk} and started processing with {method.title()}." + _documents_card(document.pk)


def process_newest(conversation):
    """Used by the agent's process_document tool: same as the 'process' command, whatever the wording."""
    pdf = _newest_pending_pdf(conversation)
    if pdf is None:
        return "There is no unprocessed PDF in this conversation. Ask the user to upload one with the 'Upload document' button."
    return _process(conversation, pdf)


def restart_process(conversation, name):
    """Run the temporary 'process' again on the uploaded PDF called `name` (the card's Restart button).
    None if that PDF is no longer in the conversation."""
    if name.lower().startswith(("http://", "https://")):
        return _process_link(name)  # a link run: fetch and process it again
    pdf = next((p for p in conversation_pdfs(conversation) if file_display_name(p.file.name) == name), None)
    return _process(conversation, pdf) if pdf else None


def save_newest(conversation, method):
    """Used by the agent's save_document tool. Without a method it asks which one, like the 'save' command."""
    pdf = _newest_pending_pdf(conversation)
    if pdf is None:
        return "There is no unsaved PDF in this conversation (it was already saved, or none was uploaded)."
    method = (method or "").strip().lower()
    if method not in ("celery", "temporal", "kafka"):
        return f"Saving '{file_display_name(pdf.file.name)}' as a document. {SAVE_METHOD_QUESTION}"
    return _save(conversation, pdf, method)


def _process_link(url):
    """Temporary Temporal run for a link (nothing saved to Documents): the fetched text is kept in a file the
    worker reads like a PDF, and the live run card shows its progress; the summary follows when it finishes.
    If Temporal cannot be reached the summary is made straight away instead."""
    try:
        page_text, pdf_file, _is_pdf = fetch_url_text(url)
    except UrlFetchError as error:
        return f"Could not read the link: {error}."
    folder = f"chat_uploads/links/{uuid.uuid4().hex}"
    stored = default_storage.save(f"{folder}.pdf", pdf_file) if pdf_file else default_storage.save(f"{folder}.txt", ContentFile(page_text.encode("utf-8")))
    try:
        workflow_id = start_pdf_extract(default_storage.path(stored))
    except Exception:
        logger.exception("Temporal could not start processing %s", url)
        return (
            f"Temporal could not be reached, so here is a quick summary of {url} (nothing was saved; "
            f"say **save {url}** to store it as a document):\n\n{_summarize(url, page_text)}"
        )
    return (
        f"{_processed_marker(url)} (workflow id {workflow_id}). Nothing is saved to your documents: "
        f"say **save {url}** to keep it. The summary follows when the run finishes."
        f"{_process_card(workflow_id, url)}"
    )


def _handle_url(conversation, text):
    """A link in the message, like the PDF commands:
    - a link alone, or with 'process'  -> temporary Temporal run with a live card, then a summary; nothing is saved
    - 'save' + link                    -> store it as a Document and process it (Temporal unless
                                          the message names Celery or Kafka)
    None if the message is not such a command."""
    found = _URL.search(text)
    if not found or len(text.split()) > MAX_NATURAL_WORDS or _QUESTION.match(text):
        return None
    rest = text.replace(found.group(0), " ")  # a "process" inside the link itself must not count
    verb = _VERB.search(rest)
    if rest.strip() and not verb:
        return None  # a link plus other words needs "process"/"save"
    url = found.group(0).rstrip(".,;:!?)]}\"'")
    if verb and verb.group(1).lower() == "save":
        method = _METHOD.search(rest)
        method = method.group(1).lower() if method else "temporal"
        document, error = register_url_for_processing(url, conversation.user, method=method)
        if document is None:
            return f"Could not save the link: {error}."
        if error:
            return f"The link was {error}." + _documents_card(document.pk)
        return f"Fetched the link, saved it as document #{document.pk} and started processing with {method.title()}." + _documents_card(document.pk)
    return _process_link(url)


def handle_command(conversation, text):
    """Reply text if `text` is a process/save command (or the answer to the save-method question)
    for a PDF in this conversation; None means: not a command, let the agent answer."""
    url_reply = _handle_url(conversation, text)
    if url_reply is not None:
        return url_reply
    pdf = _newest_pending_pdf(conversation)
    awaiting = _is_awaiting_save_method(conversation)
    if awaiting:
        method = _METHOD.search(text)
        if method and pdf:
            return _save(conversation, pdf, method.group(1).lower())
        if method:
            return "There is no unsaved PDF in this conversation (it was already saved, or none was uploaded)."
    command = _COMMAND.match(text)
    verb = command.group(1).lower() if command and len(text.split()) <= MAX_COMMAND_WORDS else None
    if verb is None and pdf is not None and len(text.split()) <= MAX_NATURAL_WORDS and not _QUESTION.match(text):
        natural = _VERB.search(text)
        if natural and _TARGET.search(text):
            verb = natural.group(1).lower()
    if verb is None:
        return None
    if pdf is None:
        return f"There is no unsaved PDF to {verb}. Upload a PDF with the 'Upload document' button first."
    if verb == "process":
        return _process(conversation, pdf)
    method = _METHOD.search(text)
    if method:
        return _save(conversation, pdf, method.group(1).lower())
    return f"Saving '{file_display_name(pdf.file.name)}' as a document. {SAVE_METHOD_QUESTION}"
