from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from tenants.models import Licencia, Tenant


def superuser_client():
    user = get_user_model().objects.create_superuser('root', 'root@delismart.test', 'clave-segura-123')
    client = APIClient()
    client.force_authenticate(user)
    return client


def make_tenant(subdominio='elsabrosito', **overrides):
    defaults = {'nombre': subdominio.title(), 'plan_id': 'pro', 'estado': Tenant.Status.ACTIVE}
    return Tenant.objects.create(subdominio=subdominio, **{**defaults, **overrides})


def make_license(tenant, days_left=20, **overrides):
    today = timezone.localdate()
    defaults = {
        'plan': tenant.plan_id,
        'fecha_inicio': today - timedelta(days=10),
        'fecha_vencimiento': today + timedelta(days=days_left),
    }
    return Licencia.objects.create(restaurante=tenant, **{**defaults, **overrides})
