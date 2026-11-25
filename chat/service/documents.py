import io
import ipaddress
import logging
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests
from django.core.files.base import ContentFile
from pypdf import PdfReader

from rag.models import Document
from rag.service.kafka_events import publish_process_request
from rag.tasks import process_document_task
from rag.temporal.client import start_document_processing

logger = logging.getLogger(__name__)


SAVE_METHODS = {
    "temporal": lambda document: start_document_processing(document.pk),
    "celery": lambda document: process_document_task.delay(document.pk),
    "kafka": lambda document: publish_process_request(document),
}


def register_pdf_for_processing(uploaded, user, method="temporal"):
    """Store an uploaded PDF as a Document and start its processing with `method`
    (temporal, celery or kafka). Returns (document, error); error is '' on success.
    The document is kept even when the chosen method cannot be reached."""
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(uploaded).pages)
    except Exception:
        return None, "the PDF could not be read for processing"
    if not text.strip():
        return None, "no text was found in the PDF for processing"
    uploaded.seek(0)
    document = Document.objects.create(
        company=user.current_company, source_type="pdf", file=uploaded, raw_text=text,
        status="pending", created_by=user, updated_by=user,
    )
    return document, start_processing(document, method)


def start_processing(document, method):
    """Set the document to pending and start `method` for it. Returns '' on success, else why it could not start.
    The document is kept even when the chosen method cannot be reached."""
    Document.objects.filter(pk=document.pk).update(status="pending")
    try:
        SAVE_METHODS[method](document)
    except Exception:
        logger.exception("Could not start %s for document %s", method, document.pk)
        return f"saved as document #{document.pk}, but {method.title()} could not be reached"
    Document.objects.filter(pk=document.pk).update(processed_via=method)
    return ""


# ---- Documents from a web link (chat: "process https://...") ----

URL_FETCH_TIMEOUT = 15
URL_MAX_BYTES = 20 * 1024 * 1024
URL_MAX_REDIRECTS = 3


class UrlFetchError(Exception):
    """The link could not be fetched; the message is safe to show the user."""


def _check_public_url(url):
    """Only http(s) links to public addresses: the server must not be pointed at localhost or the internal network."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise UrlFetchError("Only http and https links can be processed.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parts.hostname, parts.port or 443 if parts.scheme == "https" else parts.port or 80)}
    except socket.gaierror:
        raise UrlFetchError("The link's address could not be found.")
    if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
        raise UrlFetchError("That link points to a private or internal address, so it was not fetched.")


def _download(url):
    """(final_url, content_type, bytes, encoding). Redirects are followed by hand so every hop is checked."""
    for _ in range(URL_MAX_REDIRECTS + 1):
        _check_public_url(url)
        try:
            response = requests.get(url, timeout=URL_FETCH_TIMEOUT, stream=True, allow_redirects=False)
        except requests.RequestException:
            raise UrlFetchError("The link could not be reached.")
        with response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if not response.ok:
                raise UrlFetchError(f"The link answered with an error (HTTP {response.status_code}).")
            data = b""
            for chunk in response.iter_content(65536):
                data += chunk
                if len(data) > URL_MAX_BYTES:
                    raise UrlFetchError(f"The file is too large ({URL_MAX_BYTES // (1024 * 1024)} MB max).")
            return url, response.headers.get("Content-Type", ""), data, response.encoding
    raise UrlFetchError("The link redirects too many times.")


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _html_to_text(html):
    extractor = _TextExtractor()
    extractor.feed(html)
    return "\n".join(extractor.parts)


def fetch_url_text(url):
    """Fetch a PDF or web page and return (text, file, is_pdf). `file` is a ContentFile for PDFs, else None.
    Raises UrlFetchError with a message safe to show the user."""
    final_url, content_type, data, encoding = _download(url)
    is_pdf = "pdf" in content_type.lower() or urlsplit(final_url).path.lower().endswith(".pdf")
    file = None
    if is_pdf:
        try:
            text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
        except Exception:
            raise UrlFetchError("the PDF at the link could not be read")
        file = ContentFile(data, name=os.path.basename(urlsplit(final_url).path) or "document.pdf")
    else:
        text = data.decode(encoding or "utf-8", errors="replace")
        if "html" in content_type.lower() or text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
            text = _html_to_text(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise UrlFetchError("no text was found at the link")
    return text, file, is_pdf


def register_url_for_processing(url, user, method="temporal"):
    """Fetch a PDF or web page from `url`, store it as a Document and start its processing with `method`.
    Returns (document, error); error is '' on success."""
    try:
        text, file, is_pdf = fetch_url_text(url)
    except UrlFetchError as error:
        return None, str(error)
    document = Document.objects.create(
        company=user.current_company, source_type="pdf" if is_pdf else "scrape", file=file, raw_text=text,
        status="pending", created_by=user, updated_by=user,
    )
    return document, start_processing(document, method)
