from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

LOGIN_URL = '/api/v1/admin/auth/login/'


class LoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()
        users = get_user_model().objects
        users.create_superuser('root', 'root@delismart.test', 'clave-segura-123')
        users.create_user('elsabrosito', 'dueno@example.com', 'clave-segura-123')

    def login(self, username, password='clave-segura-123'):
        return self.api.post(LOGIN_URL, {'username': username, 'password': password}, format='json')

    def test_superuser_gets_tokens_that_open_the_api(self):
        response = self.login('root')
        self.assertEqual(response.status_code, 200)

        self.api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        profile = self.api.get('/api/v1/admin/auth/me/')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['username'], 'root')

    def test_refresh_returns_new_access_token(self):
        refresh = self.login('root').data['refresh']
        response = self.api.post('/api/v1/admin/auth/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    def test_restaurant_owner_cannot_log_in(self):
        self.assertEqual(self.login('elsabrosito').status_code, 401)

    def test_wrong_password_is_rejected(self):
        response = self.login('root', 'otra')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['detail'], 'Usuario o contraseña incorrectos.')

    def test_anonymous_request_is_rejected(self):
        self.assertEqual(self.api.get('/api/v1/admin/auth/me/').status_code, 401)

    def test_health_is_public(self):
        response = self.api.get('/api/v1/admin/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'status': 'ok'})
