from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0002_licencias_y_pagos'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='login_issued_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
