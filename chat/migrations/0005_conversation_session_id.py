import uuid

from django.db import migrations, models


def populate_session_id(apps, schema_editor):
    Conversation = apps.get_model('chat', 'Conversation')
    for conversation in Conversation.objects.all():
        conversation.session_id = uuid.uuid4()
        conversation.save(update_fields=['session_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0004_remove_message_referenced_scrapper_items'),
    ]

    operations = [
        migrations.AddField(
            model_name='conversation',
            name='session_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, null=True),
        ),
        migrations.RunPython(populate_session_id, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='conversation',
            name='session_id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
