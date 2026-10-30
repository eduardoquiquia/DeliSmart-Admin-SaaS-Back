from django.apps import AppConfig
from django.conf import settings


def allow_landing_checkout(sender, request, **kwargs):
    """El landing solo puede llamar al checkout: el resto de la API es exclusiva del panel."""
    return request.path.startswith('/api/stripe/') and request.headers.get('Origin') == settings.LANDING_URL


class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'

    def ready(self):
        from corsheaders.signals import check_request_enabled

        check_request_enabled.connect(allow_landing_checkout)
