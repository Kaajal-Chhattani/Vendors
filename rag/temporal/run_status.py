import math
from datetime import datetime, timezone

from asgiref.sync import async_to_sync
from django.conf import settings
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.converter import DataConverter
from temporalio.service import RPCError, RPCStatusCode

from rag.temporal.workflows import BATCH_SIZE

BATCH_ACTIVITY = 'embed_and_save_batch'
PREVIEW_BATCH_ACTIVITY = 'preview_embed_batch'  # the chat's temporary 'process' run embeds without saving
BATCH_ACTIVITIES = (BATCH_ACTIVITY, PREVIEW_BATCH_ACTIVITY)
STEPS = ('claim_document', 'prepare_chunks', BATCH_ACTIVITY, 'mark_status', 'notify_document')
EXTRACT_STEPS = ('extract_pdf_text', 'split_text_preview', PREVIEW_BATCH_ACTIVITY)  # the chat's temporary 'process' run (ExtractPdfTextWorkflow)


def _workflow_id(document_id):
    return f'document-{document_id}'


def _to_datetime(timestamp):
    return timestamp.ToDatetime() if timestamp.seconds or timestamp.nanos else None


def _failure_reason(failure):
    """Innermost message: the activity's own error, not Temporal's 'Activity task failed' wrapper."""
    while failure.HasField('cause'):
        failure = failure.cause
    return failure.message


def _new_activity(scheduled_event):
    attrs = scheduled_event.activity_task_scheduled_event_attributes
    return {
        'name': attrs.activity_type.name,
        'input_payloads': attrs.input.payloads,
        'status': 'running',
        'attempt': 1,
        'started': _to_datetime(scheduled_event.event_time),
        'ended': None,
        'error': '',
    }


def _collect_activities(events):
    """One entry per scheduled activity, in schedule order, from the closed events in the history."""
    activities = {}
    for event in events:
        if event.HasField('activity_task_scheduled_event_attributes'):
            activities[event.event_id] = _new_activity(event)
        elif event.HasField('activity_task_started_event_attributes'):
            attrs = event.activity_task_started_event_attributes
            entry = activities.get(attrs.scheduled_event_id)
            if entry:
                entry['attempt'] = attrs.attempt
                if attrs.HasField('last_failure'):
                    entry['error'] = _failure_reason(attrs.last_failure)
        elif event.HasField('activity_task_completed_event_attributes'):
            attrs = event.activity_task_completed_event_attributes
            entry = activities.get(attrs.scheduled_event_id)
            if entry:
                entry.update(status='done', ended=_to_datetime(event.event_time), error='', result_payloads=attrs.result.payloads)
        elif event.HasField('activity_task_failed_event_attributes'):
            attrs = event.activity_task_failed_event_attributes
            entry = activities.get(attrs.scheduled_event_id)
            if entry:
                entry.update(status='failed', ended=_to_datetime(event.event_time), error=_failure_reason(attrs.failure))
        elif event.HasField('activity_task_timed_out_event_attributes'):
            attrs = event.activity_task_timed_out_event_attributes
            entry = activities.get(attrs.scheduled_event_id)
            if entry:
                entry.update(status='failed', ended=_to_datetime(event.event_time), error=_failure_reason(attrs.failure) or 'Timed out')
    return list(activities.items())


def _apply_pending(activities, pending_activities):
    """Activities that are mid-retry are not closed in the history; take attempt and last error from describe()."""
    for _event_id, entry in activities:
        if entry['status'] != 'running':
            continue
        for pending in pending_activities:
            if pending.activity_type.name == entry['name'] and pending.attempt >= entry['attempt']:
                entry['attempt'] = pending.attempt
                if pending.HasField('last_failure'):
                    entry['status'] = 'retrying'
                    entry['error'] = _failure_reason(pending.last_failure)
                    entry['next_retry'] = _to_datetime(pending.scheduled_time)
                break


async def _decode(payloads):
    return await DataConverter.default.decode(payloads)


async def _label_batches(activities):
    """Turn the stored input [document_id, start, end] of each batch into a '0-20' label."""
    for _event_id, entry in activities:
        if entry['name'] in BATCH_ACTIVITIES:
            _doc, start, end = await _decode(entry['input_payloads'])
            entry['label'] = f'{start}-{end}'


def _duration(entry, now):
    if not entry['started']:
        return None
    return round(((entry['ended'] or now) - entry['started']).total_seconds(), 1)


def _public(entry, now):
    return {
        'label': entry.get('label', ''),
        'status': entry['status'],
        'attempt': entry['attempt'],
        'started': entry['started'].isoformat(sep=' ', timespec='seconds') if entry['started'] else '',
        'ended': entry['ended'].isoformat(sep=' ', timespec='seconds') if entry['ended'] else '',
        'duration': _duration(entry, now),
        'next_retry': entry['next_retry'].isoformat(sep=' ', timespec='seconds') if entry.get('next_retry') else '',
        'error': entry['error'] if entry['status'] in ('failed', 'retrying') else '',
    }


def _step_summary(name, entries, workflow_running, total_batches, now):
    if not entries:
        return {'name': name, 'status': 'pending' if workflow_running else 'not_run', 'attempt': 0, 'started': '',
                'ended': '', 'duration': None, 'next_retry': '', 'error': '', 'summary': '', 'batches': []}
    rows = [_public(e, now) for e in entries]
    if name not in BATCH_ACTIVITIES:
        return {'name': name, **rows[0], 'summary': '', 'batches': []}

    statuses = {r['status'] for r in rows}
    done = sum(1 for r in rows if r['status'] == 'done')
    if 'failed' in statuses:
        status = 'failed'
    elif 'retrying' in statuses:
        status = 'retrying'
    elif done == total_batches:
        status = 'done'
    else:
        status = 'running'
    errors = [r['error'] for r in rows if r['error']]
    return {
        'name': name, 'status': status, 'attempt': max(r['attempt'] for r in rows),
        'started': min(r['started'] for r in rows), 'ended': max(r['ended'] for r in rows) if status == 'done' else '',
        'duration': round(sum(r['duration'] or 0 for r in rows), 1), 'next_retry': '',
        'error': errors[-1] if errors else '',
        'summary': f'{done}/{total_batches} batches done',
        'batches': rows,
    }


async def _fetch(workflow_id):
    client = await Client.connect(settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE)
    handle = client.get_workflow_handle(workflow_id)
    try:
        description = await handle.describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return None
        raise
    history = await handle.fetch_history()
    return description, history.events


async def _build(workflow_id, step_names=STEPS):
    fetched = await _fetch(workflow_id)
    if fetched is None:
        return None
    description, events = fetched
    activities = _collect_activities(events)
    _apply_pending(activities, description.raw_description.pending_activities)
    await _label_batches(activities)

    chunk_count = 0
    for _event_id, entry in activities:
        if entry['name'] in ('prepare_chunks', 'split_text_preview') and entry['status'] == 'done':
            chunk_count = (await _decode(entry['result_payloads']))[0]
    total_batches = math.ceil(chunk_count / BATCH_SIZE) if chunk_count else 0

    workflow_running = description.status == WorkflowExecutionStatus.RUNNING
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    steps = [
        _step_summary(name, [e for _id, e in activities if e['name'] == name], workflow_running, total_batches, now)
        for name in step_names
    ]
    for step in steps:
        if step['name'] in ('prepare_chunks', 'split_text_preview') and step['status'] == 'done' and chunk_count:
            step['summary'] = f'{chunk_count} chunks'
    return {
        'workflow_id': description.id,
        'run_id': description.run_id,
        'status': description.status.name.title() if description.status else 'Unknown',
        'started': description.start_time.replace(tzinfo=None).isoformat(sep=' ', timespec='seconds'),
        'closed': description.close_time.replace(tzinfo=None).isoformat(sep=' ', timespec='seconds') if description.close_time else '',
        'total_seconds': round(((description.close_time.replace(tzinfo=None) if description.close_time else now) - description.start_time.replace(tzinfo=None)).total_seconds(), 1),
        'chunk_count': chunk_count,
        'steps': steps,
    }


def summarize_run(run, chunk_count):
    """Plain-text recap of a run for the chat. The last step (notify_document) is the one posting it, so it is left out."""
    steps = [step for step in run['steps'] if step['name'] != 'notify_document']
    done = sum(1 for step in steps if step['status'] == 'done')
    seconds = round(sum(step['duration'] or 0 for step in steps), 1)
    lines = [f'Temporal run: {done}/{len(steps)} steps done, {chunk_count} chunks, {seconds}s']
    for step in steps:
        line = f"• {step['name']}: {step['status']}"
        if step['summary']:
            line += f" ({step['summary']})"
        if step['attempt'] > 1:
            line += f", attempt {step['attempt']}"
        if step['error']:
            line += f" - {step['error']}"
        lines.append(line)
    return '\n'.join(lines)


def get_run_status(document_id):
    """Latest Temporal run of a document as plain dicts, or None if the document never ran on Temporal."""
    return async_to_sync(_build)(_workflow_id(document_id))


def get_extract_run_status(workflow_id):
    """Run of a chat 'process' workflow (no Document behind it) as plain dicts, or None if not found."""
    return async_to_sync(_build)(workflow_id, EXTRACT_STEPS)
