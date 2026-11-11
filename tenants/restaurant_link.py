"""Comunicación con delismart-restaurant-back (panel de cada pollería).

Ambos backends comparten INTERNAL_API_TOKEN: autoriza la consulta de licencias y firma el
token de acceso directo (SSO) que el dueño usa para entrar al panel de su pollería.
"""

import uuid

from django.conf import settings
from django.core import signing

from .models import Licencia, Tenant

SSO_SALT = 'delismart.restaurant-sso'


class SSONotConfigured(Exception):
    pass


def license_state(tenant):
    """Estado de la licencia en el vocabulario de restaurant-back."""
    license_ = tenant.licencias.order_by('-fecha_inicio', '-id').first()
    if license_ is None:
        return {'estado': 'sin_licencia', 'plan': '', 'fecha_vencimiento': None}
    estado = license_.estado_actual
    # Un restaurante suspendido desde el panel no opera, aunque su licencia siga pagada.
    if tenant.estado != Tenant.Status.ACTIVE and estado == Licencia.Status.ACTIVE:
        estado = Licencia.Status.CANCELLED
    return {
        'estado': estado,
        'plan': license_.plan,
        'fecha_vencimiento': license_.fecha_vencimiento.isoformat(),
    }


def restaurant_sso_url(tenant, user):
    if not settings.INTERNAL_API_TOKEN:
        raise SSONotConfigured
    payload = {
        'jti': uuid.uuid4().hex,
        'restaurante': {
            'subdominio': tenant.subdominio,
            'nombre': tenant.nombre,
            'ruc': tenant.ruc,
            'telefono': tenant.telefono,
        },
        'usuario': {
            'email': user.email or tenant.email_admin,
            'first_name': user.first_name,
            'last_name': user.last_name,
        },
        'licencia': license_state(tenant),
    }
    token = signing.dumps(payload, key=settings.INTERNAL_API_TOKEN, salt=SSO_SALT)
    return f'{settings.RESTAURANT_FRONT_URL}/sso#token={token}'
