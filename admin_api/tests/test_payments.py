from django.test import TestCase
from rest_framework.test import APIClient

from tenants.models import PagoStripe

from .helpers import make_tenant, superuser_client

URL = '/api/v1/admin/payments/'


class PaymentApiTests(TestCase):
    def setUp(self):
        self.tenant = make_tenant()
        PagoStripe.objects.create(
            restaurante=self.tenant, stripe_checkout_id='cs_1', monto='199.00', moneda='pen',
            raw_payload={'customer_details': {'email': 'dueno@example.com'}},
        )

    def test_lists_payments_without_raw_payload(self):
        row = superuser_client().get(URL).data['results'][0]

        self.assertEqual((row['stripe_checkout_id'], row['monto'], row['moneda']), ('cs_1', '199.00', 'pen'))
        self.assertEqual(row['restaurante_subdominio'], 'elsabrosito')
        self.assertNotIn('raw_payload', row)

    def test_searches_by_payment_id(self):
        api = superuser_client()
        self.assertEqual(api.get(URL, {'search': 'cs_1'}).data['count'], 1)
        self.assertEqual(api.get(URL, {'search': 'cs_9'}).data['count'], 0)

    def test_requires_superuser(self):
        self.assertEqual(APIClient().get(URL).status_code, 401)
