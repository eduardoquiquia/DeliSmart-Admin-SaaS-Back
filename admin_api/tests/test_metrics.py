from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from tenants.models import Licencia, PagoStripe, Tenant

from .helpers import make_license, make_tenant, superuser_client

URL = '/api/v1/admin/metrics/'
TODAY = date(2026, 10, 30)


@patch('django.utils.timezone.localdate', return_value=TODAY)
class MetricsTests(TestCase):
    def setUp(self):
        self.api = superuser_client()

    def test_empty_platform(self, _):
        data = self.api.get(URL).data

        self.assertEqual(data['restaurantes_activos'], 0)
        self.assertEqual(data['mrr'], 0)
        self.assertEqual(data['ratio_cancelacion'], 0)
        self.assertEqual(data['ingresos_totales'], 0)
        self.assertIsNone(data['pedidos_globales'])

    def test_counts_only_active_restaurants(self, _):
        make_tenant('activo1')
        make_tenant('suspendido1', estado=Tenant.Status.SUSPENDED)
        make_tenant('pendiente1', estado=Tenant.Status.PENDING)

        self.assertEqual(self.api.get(URL).data['restaurantes_activos'], 1)

    def test_mrr_uses_monthly_equivalent_and_skips_expired(self, _):
        make_license(make_tenant('mensual'))
        make_license(make_tenant('anual', billing_cycle=Tenant.BillingCycle.ANNUAL))
        make_license(make_tenant('vencido'), days_left=-1)

        # 199.00 + (1910.40 / 12)
        self.assertEqual(self.api.get(URL).data['mrr'], Decimal('358.20'))

    def test_new_subscriptions_this_month(self, _):
        make_license(make_tenant('nuevo'), fecha_inicio=date(2026, 10, 1))
        make_license(make_tenant('antiguo'), fecha_inicio=date(2026, 9, 30))

        self.assertEqual(self.api.get(URL).data['nuevas_suscripciones_mes'], 1)

    def test_cancellation_rate_is_monthly(self, _):
        started = {'fecha_inicio': date(2026, 9, 1)}
        make_license(make_tenant('a'), **started)
        make_license(make_tenant('b'), **started)
        make_license(make_tenant('c'), **started)
        make_license(
            make_tenant('d'), estado=Licencia.Status.CANCELLED, fecha_cancelacion=date(2026, 10, 5), **started,
        )

        self.assertEqual(self.api.get(URL).data['ratio_cancelacion'], 25.0)

    def test_total_income_adds_every_payment(self, _):
        tenant = make_tenant()
        for index, amount in enumerate(('103.00', '199.00')):
            PagoStripe.objects.create(
                restaurante=tenant, stripe_checkout_id=f'cs_{index}', monto=amount, moneda='pen', raw_payload={},
            )

        self.assertEqual(self.api.get(URL).data['ingresos_totales'], Decimal('302.00'))

    def test_lists_latest_payments_first(self, _):
        tenant = make_tenant()
        for index in range(6):
            PagoStripe.objects.create(
                restaurante=tenant, stripe_checkout_id=f'cs_{index}', monto='199.00', moneda='pen', raw_payload={},
            )

        rows = self.api.get(URL).data['ultimos_pagos']

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]['stripe_checkout_id'], 'cs_5')
        self.assertEqual(rows[0]['restaurante_subdominio'], 'elsabrosito')

    def test_lists_licenses_about_to_expire(self, _):
        soon = make_license(make_tenant('pronto'), days_left=3)
        make_license(make_tenant('lejos'), days_left=20)
        make_license(make_tenant('vencido'), days_left=-1)

        rows = self.api.get(URL).data['licencias_por_vencer']

        self.assertEqual([row['id'] for row in rows], [soon.id])

    def test_recent_restaurants_come_from_stripe_only(self, _):
        make_tenant('stripe1', stripe_customer_id='cus_1')
        make_tenant('manual1')

        rows = self.api.get(URL).data['ultimos_restaurantes']

        self.assertEqual([row['subdominio'] for row in rows], ['stripe1'])


class PlanListTests(TestCase):
    def test_returns_catalog_in_soles(self):
        plans = superuser_client().get('/api/v1/admin/plans/').data

        self.assertEqual([plan['id'] for plan in plans], ['expreso', 'pro', 'cadenas'])
        self.assertEqual(plans[1]['precio_mensual'], Decimal('199'))
        self.assertEqual(plans[1]['precio_anual'], Decimal('1910.40'))
