from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from tenants.models import Tenant

LOGIN_URL = '/api/v1/admin/auth/login/'
PASSWORD = 'clave-segura-123'


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        users = get_user_model().objects
        users.create_superuser('root', 'root@delismart.test', PASSWORD)
        owner = users.create_user('ana@example.com', 'ana@example.com', PASSWORD)
        Tenant.objects.create(subdominio='elsabrosito', nombre='El Sabrosito', plan_id='pro', owner=owner)
        users.create_user('suelto', 'suelto@example.com', PASSWORD)
        pending = users.create_user('pago@example.com', 'pago@example.com', PASSWORD, is_active=False)
        Tenant.objects.create(subdominio='reservado', nombre='Reservado', plan_id='pro', owner=pending)

    def login(self, username, password=PASSWORD):
        return self.api.post(LOGIN_URL, {'username': username, 'password': password}, format='json')

    def profile(self, tokens):
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        return self.api.get('/api/v1/admin/auth/me/')

    def test_superuser_logs_in_with_username_or_email(self):
        for identifier in ('root', 'ROOT@delismart.test'):
            with self.subTest(identifier=identifier):
                response = self.login(identifier)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.profile(response.data).data['rol'], 'superusuario')

    def test_owner_logs_in_as_client(self):
        response = self.login('Ana@Example.com')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.profile(response.data).data['rol'], 'cliente')

    def test_owner_cannot_reach_global_api(self):
        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {self.login('ana@example.com').data['access']}")

        for path in ('metrics/', 'tenants/', 'licenses/', 'payments/'):
            with self.subTest(path=path):
                self.assertEqual(self.api.get(f'/api/v1/admin/{path}').status_code, 403)
        self.assertEqual(self.api.post('/api/v1/admin/stripe/sync/').status_code, 403)

    def test_refresh_returns_new_access_token(self):
        refresh = self.login('root').data['refresh']
        response = self.api.post('/api/v1/admin/auth/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_user_without_restaurant_cannot_log_in(self):
        self.assertEqual(self.login('suelto').status_code, 401)

    def test_unpaid_owner_cannot_log_in(self):
        self.assertEqual(self.login('pago@example.com').status_code, 401)

    def test_wrong_password_is_rejected(self):
        response = self.login('root', 'otra')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['detail'], 'Correo o contraseña incorrectos.')

    def test_anonymous_request_is_rejected(self):
        self.assertEqual(self.api.get('/api/v1/admin/auth/me/').status_code, 401)

    def test_health_is_public(self):
        response = self.api.get('/api/v1/admin/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok'})
