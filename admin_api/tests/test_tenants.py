from django.test import TestCase

from tenants.models import PagoStripe, Tenant

from .helpers import make_license, make_tenant, superuser_client

URL = '/api/v1/admin/tenants/'


class TenantApiTests(TestCase):
    def setUp(self):
        self.api = superuser_client()

    def test_list_is_paginated_with_current_license(self):
        tenant = make_tenant()
        license_ = make_license(tenant)
        for index in range(11):
            make_tenant(f'local{index}')

        response = self.api.get(URL)

        self.assertEqual(response.data['count'], 12)
        self.assertEqual(len(response.data['results']), 10)
        self.assertEqual(self.api.get(URL, {'page': 2}).data['results'][1]['licencia']['id'], license_.id)

    def test_searches_by_name_or_subdomain(self):
        make_tenant('pollosbrasa', nombre='Don Pollo')
        make_tenant('elsabrosito', nombre='Sabrosito')

        self.assertEqual(self.api.get(URL, {'search': 'brasa'}).data['count'], 1)
        self.assertEqual(self.api.get(URL, {'search': 'sabros'}).data['count'], 1)

    def test_filters_by_status(self):
        make_tenant('activo1')
        make_tenant('suspendido1', estado=Tenant.Status.SUSPENDED)

        response = self.api.get(URL, {'estado': 'suspendido'})

        self.assertEqual([row['subdominio'] for row in response.data['results']], ['suspendido1'])

    def test_creates_active_tenant(self):
        response = self.api.post(URL, {'nombre': 'Nuevo', 'subdominio': 'nuevo', 'plan_id': 'pro'}, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['estado'], 'activo')

    def test_rejects_invalid_and_duplicated_subdomains(self):
        make_tenant('ocupado')
        for subdominio in ('www', 'Con Espacios', 'ocupado'):
            with self.subTest(subdominio=subdominio):
                response = self.api.post(URL, {'nombre': 'X', 'subdominio': subdominio, 'plan_id': 'pro'}, format='json')
                self.assertEqual(response.status_code, 400)

    def test_edits_data_and_suspends(self):
        tenant = make_tenant()

        response = self.api.patch(f'{URL}{tenant.id}/', {'ruc': '20123456789', 'estado': 'suspendido'}, format='json')

        self.assertEqual(response.status_code, 200)
        tenant.refresh_from_db()
        self.assertEqual((tenant.ruc, tenant.estado), ('20123456789', Tenant.Status.SUSPENDED))

    def test_unpaid_tenant_cannot_be_activated_or_renamed(self):
        tenant = make_tenant('reservado', estado=Tenant.Status.PENDING)

        for payload in ({'estado': 'activo'}, {'subdominio': 'otro-nombre'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.api.patch(f'{URL}{tenant.id}/', payload, format='json').status_code, 400)

    def test_active_tenant_cannot_return_to_pending(self):
        tenant = make_tenant()
        self.assertEqual(self.api.patch(f'{URL}{tenant.id}/', {'estado': 'pendiente'}, format='json').status_code, 400)

    def test_tenant_with_payments_cannot_be_deleted(self):
        tenant = make_tenant()
        PagoStripe.objects.create(
            restaurante=tenant, stripe_checkout_id='cs_1', monto=199, moneda='pen', raw_payload={},
        )

        self.assertEqual(self.api.delete(f'{URL}{tenant.id}/').status_code, 409)

    def test_tenant_without_payments_can_be_deleted(self):
        tenant = make_tenant()
        self.assertEqual(self.api.delete(f'{URL}{tenant.id}/').status_code, 204)
