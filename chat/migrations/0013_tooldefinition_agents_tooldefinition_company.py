from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('company', '0001_initial'),
        ('chat', '0012_order'),
    ]

    operations = [
        migrations.AddField(
            model_name='tooldefinition',
            name='agents',
            field=models.ManyToManyField(blank=True, related_name='tools', to='chat.agent'),
        ),
        migrations.AddField(
            model_name='tooldefinition',
            name='company',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tools', to='company.company'),
        ),
    ]
