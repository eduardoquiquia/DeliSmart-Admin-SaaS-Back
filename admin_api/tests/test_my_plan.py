from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from tenants.models import PagoStripe

from .helpers import make_license, make_tenant, superuser_client

URL = '/api/v1/admin/my-plan/'


class MyPlanTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user('ana@example.com', 'ana@example.com', 'clave-segura-123')
        self.tenant = make_tenant(owner=self.owner)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)

    def test_returns_only_own_restaurant_license_and_payments(self):
        license_ = make_license(self.tenant)
        other = make_tenant('otro')
        PagoStripe.objects.create(
            restaurante=self.tenant, stripe_checkout_id='cs_1', monto=199, moneda='pen', raw_payload={},
        )
        PagoStripe.objects.create(
            restaurante=other, stripe_checkout_id='cs_2', monto=199, moneda='pen', raw_payload={},
        )

        data = self.api.get(URL).data

        self.assertEqual(data['restaurante']['subdominio'], 'elsabrosito')
        self.assertEqual(data['licencia']['id'], license_.id)
        self.assertEqual([row['stripe_checkout_id'] for row in data['pagos']], ['cs_1'])

    def test_handles_restaurant_without_license(self):
        self.assertIsNone(self.api.get(URL).data['licencia'])

    def test_requires_a_restaurant(self):
        self.assertEqual(superuser_client().get(URL).status_code, 403)

    def test_requires_authentication(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)

    def test_owner_reads_plan_catalog(self):
        self.assertEqual(self.api.get('/api/v1/admin/plans/').status_code, 200)
