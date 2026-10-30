import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0001_initial'),
    ]

    operations = [
        migrations.RenameField('tenant', 'restaurant_name', 'nombre'),
        migrations.RenameField('tenant', 'subdomain', 'subdominio'),
        migrations.RenameField('tenant', 'status', 'estado'),
        migrations.RenameField('tenant', 'created_at', 'fecha_creacion'),
        migrations.RemoveField('tenant', 'stripe_subscription_id'),
        migrations.AddField(
            model_name='tenant',
            name='ruc',
            field=models.CharField(blank=True, max_length=11),
        ),
        migrations.AddField(
            model_name='tenant',
            name='telefono',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='tenant',
            name='email_admin',
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.AlterField(
            model_name='tenant',
            name='plan_id',
            field=models.CharField(
                choices=[('expreso', 'Expreso'), ('pro', 'Pro Restaurante'), ('cadenas', 'Cadenas')],
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='Licencia',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('plan', models.CharField(
                    choices=[('expreso', 'Expreso'), ('pro', 'Pro Restaurante'), ('cadenas', 'Cadenas')],
                    max_length=20,
                )),
                ('fecha_inicio', models.DateField()),
                ('fecha_vencimiento', models.DateField()),
                ('monto_pagado', models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ('estado', models.CharField(
                    choices=[('activa', 'Activa'), ('vencida', 'Vencida'), ('cancelada', 'Cancelada')],
                    default='activa',
                    max_length=10,
                )),
                ('fecha_cancelacion', models.DateField(blank=True, null=True)),
                ('stripe_subscription_id', models.CharField(blank=True, db_index=True, max_length=255)),
                ('restaurante', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='licencias',
                    to='tenants.tenant',
                )),
            ],
            options={'verbose_name_plural': 'licencias'},
        ),
        migrations.CreateModel(
            name='PagoStripe',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stripe_checkout_id', models.CharField(max_length=255, unique=True)),
                ('monto', models.DecimalField(decimal_places=2, max_digits=10)),
                ('moneda', models.CharField(max_length=3)),
                ('fecha_pago', models.DateTimeField(default=django.utils.timezone.now)),
                ('raw_payload', models.JSONField()),
                ('restaurante', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='pagos',
                    to='tenants.tenant',
                )),
            ],
            options={'verbose_name_plural': 'pagos de Stripe'},
        ),
    ]
