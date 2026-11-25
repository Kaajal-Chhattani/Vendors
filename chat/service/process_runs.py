"""Stop / restart a chat 'process' run (temporary Temporal run, no Document).

One code path for the card buttons (views.ProcessRunStopView / ProcessRunRestartView) and the
agent tools (stop_process_run / restart_process_run). Both return (ok, message[, content]).
"""
import json
import logging
import re

from chat.models import Message
from rag.temporal.client import stop_pdf_extract
from rag.temporal.run_status import get_extract_run_status

logger = logging.getLogger(__name__)

_INTRO_NAME = re.compile(r"Processing '(.*?)' with Temporal")
_RUN_FENCE = re.compile(r"```processrun\n([\s\S]*?)```")


def find_intro(user, workflow_id):
    """The assistant message that announced this run, if it is the user's own."""
    return Message.objects.filter(
        conversation__user=user, role='assistant', content__startswith='Processing', content__contains=workflow_id,
    ).select_related('conversation').first()


def newest_run_id(conversation):
    """Workflow id of the newest process run shown in this conversation, or None."""
    for message in conversation.messages.filter(role='assistant', content__contains='```processrun').order_by('-id')[:20]:
        match = _RUN_FENCE.search(message.content)
        if match:
            try:
                return json.loads(match.group(1))['id']
            except (ValueError, KeyError):
                continue
    return None


def conversation_runs(conversation, limit=5):
    """The newest process runs shown in this conversation, newest first, as [{'id', 'name'}]."""
    runs = []
    for message in conversation.messages.filter(role='assistant', content__contains='```processrun').order_by('-id')[:20]:
        for match in _RUN_FENCE.finditer(message.content):
            try:
                spec = json.loads(match.group(1))
                runs.append({'id': spec['id'], 'name': spec.get('name', '')})
            except (ValueError, KeyError):
                continue
    return runs[:limit]


def stop_run(user, workflow_id):
    """Cancel a running process run. Returns (ok, message, http_status)."""
    if not find_intro(user, workflow_id):
        return False, 'Run not found.', 404
    try:
        stopped = stop_pdf_extract(workflow_id)
    except Exception:
        logger.exception('Could not stop process run %s', workflow_id)
        return False, 'Could not reach Temporal to stop it.', 502
    if not stopped:
        return False, 'It is not running any more.', 409
    return True, 'Stopped.', 200


def restart_run(user, workflow_id):
    """Run a stopped/failed process run again as a new run. Returns (ok, message_or_content, http_status);
    on success the text is the new assistant message (with its own live card), already saved in the chat."""
    intro = find_intro(user, workflow_id)
    if not intro:
        return False, 'Run not found.', 404
    try:
        run = get_extract_run_status(workflow_id)
    except Exception:
        logger.exception('Could not read process run %s', workflow_id)
        return False, 'Could not reach Temporal.', 502
    if run and run['status'] == 'Running':
        return False, 'It is still running.', 409
    match = _INTRO_NAME.search(intro.content)
    from chat.service.commands import restart_process  # lazy: commands imports a lot
    content = restart_process(intro.conversation, match.group(1) if match else '')
    if content is None:
        return False, 'The PDF is no longer in this chat.', 404
    Message.objects.create(
        conversation=intro.conversation, content=content, role='assistant',
        session_id=intro.conversation.session_id, user=user, company=intro.conversation.company,
    )
    return True, content, 200
