from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0014_populate_tooldefinition_company_and_agents'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='tooldefinition',
            unique_together=set(),
        ),
        migrations.RemoveField(
            model_name='tooldefinition',
            name='agent',
        ),
        migrations.AlterField(
            model_name='tooldefinition',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tools', to='company.company'),
        ),
        migrations.AlterUniqueTogether(
            name='tooldefinition',
            unique_together={('company', 'name')},
        ),
    ]
