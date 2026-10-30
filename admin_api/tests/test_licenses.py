from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from tenants.models import Licencia

from .helpers import make_license, make_tenant, superuser_client

URL = '/api/v1/admin/licenses/'


class LicenseApiTests(TestCase):
    def setUp(self):
        self.api = superuser_client()
        self.tenant = make_tenant()

    def test_filters_treat_past_due_license_as_expired(self):
        current = make_license(self.tenant)
        expired = make_license(make_tenant('vencido'), days_left=-3)
        cancelled = make_license(make_tenant('cancelado'), estado=Licencia.Status.CANCELLED)

        def ids(estado):
            return [row['id'] for row in self.api.get(URL, {'estado': estado}).data['results']]

        self.assertEqual(ids('activa'), [current.id])
        self.assertEqual(ids('vencida'), [expired.id])
        self.assertEqual(ids('cancelada'), [cancelled.id])
        row = self.api.get(f'{URL}{expired.id}/').data
        self.assertEqual((row['estado'], row['dias_restantes']), ('vencida', -3))

    def test_changing_plan_updates_the_tenant_too(self):
        license_ = make_license(self.tenant)

        response = self.api.patch(f'{URL}{license_.id}/', {'plan': 'cadenas'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.plan_id, 'cadenas')

    def test_extends_validity(self):
        license_ = make_license(self.tenant)
        new_end = timezone.localdate() + timedelta(days=90)

        self.api.patch(f'{URL}{license_.id}/', {'fecha_vencimiento': new_end}, format='json')

        license_.refresh_from_db()
        self.assertEqual(license_.fecha_vencimiento, new_end)

    def test_rejects_end_before_start(self):
        license_ = make_license(self.tenant)
        before = license_.fecha_inicio - timedelta(days=1)
        response = self.api.patch(f'{URL}{license_.id}/', {'fecha_vencimiento': before}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_cancelling_sets_date_and_reactivating_clears_it(self):
        license_ = make_license(self.tenant)

        self.api.patch(f'{URL}{license_.id}/', {'estado': 'cancelada'}, format='json')
        license_.refresh_from_db()
        self.assertEqual(license_.fecha_cancelacion, timezone.localdate())

        self.api.patch(f'{URL}{license_.id}/', {'estado': 'activa'}, format='json')
        license_.refresh_from_db()
        self.assertIsNone(license_.fecha_cancelacion)

    def test_creates_and_deletes(self):
        today = timezone.localdate()
        response = self.api.post(URL, {
            'restaurante': self.tenant.id,
            'plan': 'expreso',
            'fecha_inicio': today,
            'fecha_vencimiento': today + timedelta(days=30),
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.api.delete(f"{URL}{response.data['id']}/").status_code, 204)
