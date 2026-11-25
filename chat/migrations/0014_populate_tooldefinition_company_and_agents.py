from django.db import migrations


def populate(apps, schema_editor):
    ToolDefinition = apps.get_model('chat', 'ToolDefinition')
    for tool in ToolDefinition.objects.select_related('agent').all():
        if tool.agent_id:
            tool.company_id = tool.agent.company_id
            tool.save(update_fields=['company'])
            tool.agents.add(tool.agent_id)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0013_tooldefinition_agents_tooldefinition_company'),
    ]

    operations = [
        migrations.RunPython(populate, noop_reverse),
    ]
