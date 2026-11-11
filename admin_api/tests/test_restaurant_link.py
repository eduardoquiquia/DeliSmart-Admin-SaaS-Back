from django.contrib.auth import get_user_model
from django.core import signing
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from tenants.models import Tenant
from tenants.restaurant_link import SSO_SALT

from .helpers import make_license, make_tenant, superuser_client

ACCESS_URL = '/api/v1/admin/my-plan/restaurant-access/'
TOKEN = 'token-interno-de-prueba'


@override_settings(INTERNAL_API_TOKEN=TOKEN, RESTAURANT_FRONT_URL='https://pos.example.com')
class RestaurantAccessTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user('ana@example.com', 'ana@example.com', 'clave-segura-123', first_name='Ana')
        self.tenant = make_tenant(owner=self.owner, ruc='20123456789')
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def _payload(self, url):
        prefix = 'https://pos.example.com/sso#token='
        self.assertTrue(url.startswith(prefix))
        return signing.loads(url.removeprefix(prefix), key=TOKEN, salt=SSO_SALT)

    def test_signs_restaurant_owner_and_license(self):
        license_ = make_license(self.tenant)

        payload = self._payload(self.api.post(ACCESS_URL).data['url'])

        self.assertEqual(payload['restaurante']['subdominio'], 'elsabrosito')
        self.assertEqual(payload['restaurante']['ruc'], '20123456789')
        self.assertEqual(payload['usuario']['email'], 'ana@example.com')
        self.assertEqual(payload['licencia'], {
            'estado': 'activa', 'plan': 'pro', 'fecha_vencimiento': license_.fecha_vencimiento.isoformat(),
        })
        self.assertTrue(payload['jti'])

    def test_each_link_is_different(self):
        first = self.api.post(ACCESS_URL).data['url']
        self.assertNotEqual(first, self.api.post(ACCESS_URL).data['url'])

    def test_suspended_restaurant_is_cancelled(self):
        make_license(self.tenant)
        Tenant.objects.filter(pk=self.tenant.pk).update(estado=Tenant.Status.SUSPENDED)

        payload = self._payload(self.api.post(ACCESS_URL).data['url'])

        self.assertEqual(payload['licencia']['estado'], 'cancelada')

    def test_requires_a_restaurant_owner(self):
        self.assertEqual(superuser_client().post(ACCESS_URL).status_code, 403)

    @override_settings(INTERNAL_API_TOKEN='')
    def test_without_shared_token_is_unavailable(self):
        self.assertEqual(self.api.post(ACCESS_URL).status_code, 503)


@override_settings(INTERNAL_API_TOKEN=TOKEN)
class InternalLicenseTests(TestCase):
    url = '/api/internal/licencias/elsabrosito/'

    def test_returns_license_with_internal_token(self):
        license_ = make_license(make_tenant())

        response = APIClient().get(self.url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['fecha_vencimiento'], license_.fecha_vencimiento.isoformat())

    def test_restaurant_without_license(self):
        make_tenant()
        response = APIClient().get(self.url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        self.assertEqual(response.data['estado'], 'sin_licencia')

    def test_unknown_restaurant_is_404(self):
        response = APIClient().get(self.url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        self.assertEqual(response.status_code, 404)

    def test_rejects_wrong_token(self):
        make_tenant()
        self.assertEqual(APIClient().get(self.url, HTTP_AUTHORIZATION='Bearer otro').status_code, 403)
        self.assertEqual(APIClient().get(self.url).status_code, 403)
