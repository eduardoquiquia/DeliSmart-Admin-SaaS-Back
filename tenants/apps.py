from django.apps import AppConfig
from django.conf import settings

LANDING_API_PATHS = ('/api/stripe/', '/api/v1/admin/auth/login/')


def allow_landing_requests(sender, request, **kwargs):
    """El landing solo llega al checkout y al login: el resto de la API es exclusiva del panel."""
    return request.path.startswith(LANDING_API_PATHS) and request.headers.get('Origin') == settings.LANDING_URL


class TenantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tenants'

    def ready(self):
        from corsheaders.signals import check_request_enabled

        check_request_enabled.connect(allow_landing_requests)
