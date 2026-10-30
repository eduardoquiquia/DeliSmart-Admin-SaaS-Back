import hashlib
import hmac
import json
import time
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import stripe
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Licencia, PagoStripe, Tenant
from .plans import stripe_price_data
from .services import provision_tenant, sync_pending_checkouts

CHECKOUT_URL = '/api/stripe/create-checkout-session/'
WEBHOOK_URL = '/api/stripe/webhook/'
WEBHOOK_SECRET = 'whsec_unit_test'
PASSWORD = 'clave-segura-123'


def checkout_payload(**overrides):
    return {
        'plan_id': 'pro',
        'billing_cycle': 'monthly',
        'first_name': 'Ana',
        'last_name': 'Quispe',
        'email': 'Ana@Example.com',
        'phone': '+51987654321',
        'password': PASSWORD,
        'restaurant_name': 'El Sabrosito',
        'ruc': '20123456789',
        'subdomain': 'elsabrosito',
        **overrides,
    }


def stripe_client(session_id='cs_new'):
    client = MagicMock()
    client.v1.customers.create.return_value = SimpleNamespace(id='cus_new')
    sessions = client.v1.checkout.sessions
    sessions.create.return_value = SimpleNamespace(id=session_id, url=f'https://checkout.stripe.test/{session_id}')
    return client


class PlanPricingTests(TestCase):
    def test_monthly_price(self):
        price = stripe_price_data('expreso', 'monthly')
        self.assertEqual(price['unit_amount'], 10300)
        self.assertEqual(price['recurring'], {'interval': 'month'})

    def test_annual_price_has_twenty_percent_discount(self):
        price = stripe_price_data('pro', 'annual')
        self.assertEqual(price['unit_amount'], 191040)
        self.assertEqual(price['recurring'], {'interval': 'year'})


class CreateCheckoutSessionTests(TestCase):
    def setUp(self):
        cache.clear()
        self.api = APIClient()

    def post(self, client, **overrides):
        with patch('tenants.services.get_stripe_client', return_value=client):
            return self.api.post(CHECKOUT_URL, checkout_payload(**overrides), format='json')

    def test_creates_session_with_metadata_and_reserves_subdomain(self):
        client = stripe_client()
        response = self.post(client)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['checkout_url'], 'https://checkout.stripe.test/cs_new')
        params = client.v1.checkout.sessions.create.call_args.kwargs['params']
        self.assertEqual(params['metadata'], {
            'subdomain': 'elsabrosito',
            'restaurant_name': 'El Sabrosito',
            'plan_id': 'pro',
        })
        tenant = Tenant.objects.get(subdominio='elsabrosito')
        self.assertEqual(tenant.estado, Tenant.Status.PENDING)
        self.assertEqual(tenant.stripe_session_id, 'cs_new')

    def test_rejects_invalid_and_reserved_subdomains(self):
        for subdomain in ('Mi_Local', 'ab', '-abc', 'www'):
            with self.subTest(subdomain=subdomain):
                self.assertEqual(self.post(stripe_client(), subdomain=subdomain).status_code, 400)

    def test_rejects_unknown_plan(self):
        self.assertEqual(self.post(stripe_client(), plan_id='gratis').status_code, 400)

    def test_rejects_active_subdomain(self):
        Tenant.objects.create(subdominio='elsabrosito', nombre='Otro', plan_id='pro', estado=Tenant.Status.ACTIVE)
        client = stripe_client()
        self.assertEqual(self.post(client).status_code, 409)
        client.v1.checkout.sessions.create.assert_not_called()

    def test_new_checkout_expires_previous_unpaid_one(self):
        Tenant.objects.create(subdominio='elsabrosito', nombre='Otro', plan_id='expreso', stripe_session_id='cs_old')
        client = stripe_client()
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='open')

        self.assertEqual(self.post(client).status_code, 201)

        client.v1.checkout.sessions.expire.assert_called_once_with('cs_old')
        tenant = Tenant.objects.get(subdominio='elsabrosito')
        self.assertEqual((tenant.stripe_session_id, tenant.plan_id), ('cs_new', 'pro'))

    def test_rejects_subdomain_paid_while_webhook_is_in_flight(self):
        Tenant.objects.create(subdominio='elsabrosito', nombre='Otro', plan_id='pro', stripe_session_id='cs_old')
        client = stripe_client()
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='complete')

        self.assertEqual(self.post(client).status_code, 409)
        client.v1.checkout.sessions.create.assert_not_called()

    def test_stripe_failure_releases_subdomain(self):
        client = stripe_client()
        client.v1.checkout.sessions.create.side_effect = stripe.APIConnectionError('sin red')

        self.assertEqual(self.post(client).status_code, 502)
        self.assertFalse(Tenant.objects.filter(subdominio='elsabrosito').exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_registers_inactive_owner_tenant_and_stripe_customer(self):
        client = stripe_client()
        self.assertEqual(self.post(client).status_code, 201)

        tenant = Tenant.objects.get(subdominio='elsabrosito')
        owner = tenant.owner
        self.assertEqual((owner.email, owner.first_name, owner.last_name), ('ana@example.com', 'Ana', 'Quispe'))
        self.assertFalse(owner.is_active)
        self.assertTrue(owner.check_password(PASSWORD))
        self.assertEqual((tenant.ruc, tenant.telefono, tenant.email_admin), ('20123456789', '+51987654321', 'ana@example.com'))
        self.assertEqual(tenant.stripe_customer_id, 'cus_new')

        params = client.v1.checkout.sessions.create.call_args.kwargs['params']
        self.assertEqual(params['customer'], 'cus_new')
        self.assertIn('session_id={CHECKOUT_SESSION_ID}', params['success_url'])
        customer = client.v1.customers.create.call_args.kwargs['params']
        self.assertEqual((customer['email'], customer['name']), ('ana@example.com', 'Ana Quispe'))

    def test_password_is_not_sent_to_stripe(self):
        client = stripe_client()
        self.post(client)
        self.assertNotIn(PASSWORD, str(client.mock_calls))

    def test_rejects_weak_password_and_invalid_ruc(self):
        self.assertEqual(self.post(stripe_client(), password='123').status_code, 400)
        self.assertEqual(self.post(stripe_client(), ruc='123').status_code, 400)

    def test_rejects_email_of_an_active_account(self):
        get_user_model().objects.create_user('ana', 'ana@example.com', PASSWORD)
        client = stripe_client()

        response = self.post(client)

        self.assertEqual(response.status_code, 409)
        self.assertIn('email', response.data)
        client.v1.customers.create.assert_not_called()

    def test_failed_reservation_leaves_no_account(self):
        Tenant.objects.create(subdominio='elsabrosito', nombre='Otro', plan_id='pro', estado=Tenant.Status.ACTIVE)
        self.assertEqual(self.post(stripe_client()).status_code, 409)
        self.assertFalse(get_user_model().objects.exists())

    def test_same_buyer_can_retry_with_another_subdomain(self):
        client = stripe_client()
        self.post(client)
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='open')

        response = self.post(client, subdomain='otro-local', password='otra-clave-segura-456')

        self.assertEqual(response.status_code, 201)
        client.v1.checkout.sessions.expire.assert_called_once_with('cs_new')
        self.assertEqual(list(Tenant.objects.values_list('subdominio', flat=True)), ['otro-local'])
        owner = get_user_model().objects.get()
        self.assertTrue(owner.check_password('otra-clave-segura-456'))

    def test_new_buyer_replaces_unpaid_owner_of_the_subdomain(self):
        client = stripe_client()
        self.post(client)
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='open')

        self.assertEqual(self.post(client, email='luis@example.com').status_code, 201)

        owner = Tenant.objects.get(subdominio='elsabrosito').owner
        self.assertEqual(owner.email, 'luis@example.com')
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(client.v1.customers.create.call_count, 2)


class CompleteCheckoutTests(TestCase):
    URL = '/api/stripe/complete-checkout/'

    def setUp(self):
        cache.clear()
        self.owner = get_user_model().objects.create_user(
            'ana@example.com', 'ana@example.com', PASSWORD, is_active=False,
        )
        self.tenant = Tenant.objects.create(
            subdominio='elsabrosito', nombre='El Sabrosito', plan_id='pro', owner=self.owner,
            email_admin='ana@example.com', stripe_customer_id='cus_new', stripe_session_id='cs_paid',
        )

    def session(self, status='complete', payment_status='paid'):
        return stripe.checkout.Session.construct_from({
            'id': 'cs_paid',
            'object': 'checkout.session',
            'status': status,
            'payment_status': payment_status,
            'customer': 'cus_new',
            'subscription': 'sub_1',
            'customer_details': {'email': 'ana@example.com', 'phone': None},
            'amount_total': 19900,
            'currency': 'pen',
            'metadata': {'subdomain': 'elsabrosito', 'restaurant_name': 'El Sabrosito', 'plan_id': 'pro'},
        }, 'sk_test')

    def post(self, session=None, session_id='cs_paid'):
        client = MagicMock()
        client.v1.checkout.sessions.retrieve.return_value = session or self.session()
        with patch('tenants.services.get_stripe_client', return_value=client):
            return APIClient().post(self.URL, {'session_id': session_id}, format='json')

    def test_activates_owner_and_returns_working_tokens(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.is_active)
        self.assertEqual(Licencia.objects.get(restaurante=self.tenant).plan, 'pro')
        self.assertEqual(mail.outbox[0].to, ['ana@example.com'])
        self.assertNotIn(PASSWORD, mail.outbox[0].body)
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(api.get('/api/v1/admin/my-plan/').status_code, 200)

    def test_keeps_stripe_customer(self):
        self.post()
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.stripe_customer_id, 'cus_new')

    def test_session_logs_in_only_once(self):
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 410)

    def test_unpaid_session_gets_no_tokens(self):
        response = self.post(self.session(status='open', payment_status='unpaid'))

        self.assertEqual(response.status_code, 202)
        self.assertNotIn('access', response.data)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    def test_unknown_session_is_rejected(self):
        self.assertEqual(self.post(session_id='cs_other').status_code, 404)

    def test_webhook_activation_still_allows_login(self):
        provision_tenant(self.session())
        self.assertEqual(self.post().status_code, 200)


@override_settings(STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET)
class StripeWebhookTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            subdominio='elsabrosito',
            nombre='El Sabrosito',
            plan_id='pro',
            stripe_session_id='cs_paid',
        )

    def event_body(self, event_type='checkout.session.completed', session_id='cs_paid', payment_status='paid'):
        return json.dumps({
            'id': 'evt_1',
            'object': 'event',
            'type': event_type,
            'data': {'object': {
                'id': session_id,
                'object': 'checkout.session',
                'payment_status': payment_status,
                'customer': 'cus_1',
                'subscription': 'sub_1',
                'customer_details': {'email': 'dueno@example.com', 'phone': None},
                'amount_total': 19900,
                'currency': 'pen',
                'metadata': {'subdomain': 'elsabrosito', 'restaurant_name': 'El Sabrosito', 'plan_id': 'pro'},
            }},
        })

    def post(self, body, secret=WEBHOOK_SECRET):
        timestamp = int(time.time())
        digest = hmac.new(secret.encode(), f'{timestamp}.{body}'.encode(), hashlib.sha256).hexdigest()
        return self.client.post(
            WEBHOOK_URL,
            body,
            content_type='application/json',
            headers={'Stripe-Signature': f't={timestamp},v1={digest}'},
        )

    def test_rejects_invalid_signature(self):
        self.assertEqual(self.post(self.event_body(), secret='whsec_other').status_code, 400)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)

    @override_settings(STRIPE_WEBHOOK_SECRET='')
    def test_refuses_events_without_configured_secret(self):
        self.assertEqual(self.post(self.event_body(), secret='').status_code, 503)

    def test_activates_tenant_and_creates_credentials(self):
        self.assertEqual(self.post(self.event_body()).status_code, 200)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.ACTIVE)
        self.assertEqual(self.tenant.email_admin, 'dueno@example.com')
        owner = self.tenant.owner
        self.assertEqual((owner.username, owner.email), ('elsabrosito', 'dueno@example.com'))
        self.assertEqual(len(mail.outbox), 1)
        password = mail.outbox[0].body.split('Contraseña temporal: ')[1].strip()
        self.assertTrue(owner.check_password(password))

    def test_records_license_and_payment(self):
        self.post(self.event_body())

        license_ = Licencia.objects.get(restaurante=self.tenant)
        self.assertEqual(license_.plan, 'pro')
        self.assertEqual(license_.monto_pagado, Decimal('199.00'))
        self.assertEqual(license_.stripe_subscription_id, 'sub_1')
        self.assertGreater(license_.fecha_vencimiento, license_.fecha_inicio)
        payment = PagoStripe.objects.get(restaurante=self.tenant)
        self.assertEqual((payment.stripe_checkout_id, payment.moneda), ('cs_paid', 'pen'))
        self.assertEqual(payment.raw_payload['id'], 'cs_paid')

    def invoice_body(self, invoice_id='in_1', billing_reason='subscription_cycle'):
        return json.dumps({
            'id': 'evt_2',
            'object': 'event',
            'type': 'invoice.paid',
            'data': {'object': {
                'id': invoice_id,
                'object': 'invoice',
                'billing_reason': billing_reason,
                'amount_paid': 19900,
                'currency': 'pen',
                'parent': {'subscription_details': {'subscription': 'sub_1'}},
                'lines': {'object': 'list', 'data': [{'period': {'end': 1893456000}}]},
            }},
        })

    def test_renewal_extends_license_once(self):
        self.post(self.event_body())

        self.assertEqual(self.post(self.invoice_body()).status_code, 200)
        self.assertEqual(self.post(self.invoice_body()).status_code, 200)

        license_ = Licencia.objects.get(restaurante=self.tenant)
        self.assertEqual(license_.fecha_vencimiento.year, 2029)
        self.assertEqual(license_.monto_pagado, Decimal('398.00'))
        self.assertEqual(PagoStripe.objects.filter(restaurante=self.tenant).count(), 2)

    def test_first_invoice_is_not_a_renewal(self):
        self.post(self.event_body())
        self.post(self.invoice_body(billing_reason='subscription_create'))

        self.assertEqual(PagoStripe.objects.filter(restaurante=self.tenant).count(), 1)

    def test_deleted_subscription_cancels_license_and_suspends_tenant(self):
        self.post(self.event_body())
        body = json.dumps({
            'id': 'evt_3',
            'object': 'event',
            'type': 'customer.subscription.deleted',
            'data': {'object': {'id': 'sub_1', 'object': 'subscription'}},
        })

        self.assertEqual(self.post(body).status_code, 200)

        license_ = Licencia.objects.get(restaurante=self.tenant)
        self.assertEqual(license_.estado, Licencia.Status.CANCELLED)
        self.assertIsNotNone(license_.fecha_cancelacion)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.SUSPENDED)

    def test_waits_for_deferred_payment_before_activating(self):
        self.post(self.event_body(payment_status='unpaid'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)

        self.post(self.event_body(event_type='checkout.session.async_payment_succeeded'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.ACTIVE)

    def test_repeated_event_is_idempotent(self):
        self.post(self.event_body())
        self.assertEqual(self.post(self.event_body()).status_code, 200)

        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_mail_failure_rolls_back_so_stripe_retries(self):
        self.client.raise_request_exception = False
        with patch('tenants.services.send_mail', side_effect=OSError('smtp caído')):
            self.assertEqual(self.post(self.event_body()).status_code, 500)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_ignores_session_replaced_by_newer_checkout(self):
        self.assertEqual(self.post(self.event_body(session_id='cs_other')).status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)

    def test_ignores_other_events(self):
        self.assertEqual(self.post(self.event_body(event_type='customer.created')).status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)


class SyncPendingCheckoutsTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            subdominio='elsabrosito', nombre='El Sabrosito', plan_id='pro', stripe_session_id='cs_paid',
        )

    def session(self, status='complete', payment_status='paid'):
        return stripe.checkout.Session.construct_from({
            'id': 'cs_paid',
            'object': 'checkout.session',
            'status': status,
            'payment_status': payment_status,
            'customer': 'cus_1',
            'subscription': 'sub_1',
            'customer_details': {'email': 'dueno@example.com', 'phone': None},
            'amount_total': 19900,
            'currency': 'pen',
            'metadata': {'subdomain': 'elsabrosito', 'restaurant_name': 'El Sabrosito', 'plan_id': 'pro'},
        }, 'sk_test')

    def sync(self, client):
        with patch('tenants.services.get_stripe_client', return_value=client):
            return sync_pending_checkouts()

    def client_returning(self, session):
        client = MagicMock()
        client.v1.checkout.sessions.retrieve.return_value = session
        return client

    def test_activates_paid_checkout_without_webhook(self):
        self.assertEqual(self.sync(self.client_returning(self.session())), 1)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.ACTIVE)
        self.assertEqual(Licencia.objects.get(restaurante=self.tenant).plan, 'pro')
        self.assertEqual(PagoStripe.objects.get(restaurante=self.tenant).stripe_checkout_id, 'cs_paid')

    def test_is_idempotent(self):
        client = self.client_returning(self.session())

        self.sync(client)

        self.assertEqual(self.sync(client), 0)
        self.assertEqual(PagoStripe.objects.count(), 1)

    def test_leaves_unpaid_checkout_pending(self):
        self.assertEqual(self.sync(self.client_returning(self.session(status='open', payment_status='unpaid'))), 0)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.estado, Tenant.Status.PENDING)

    def test_skips_expired_checkouts(self):
        old = timezone.now() - timedelta(hours=26)
        Tenant.objects.filter(pk=self.tenant.pk).update(updated_at=old)
        client = self.client_returning(self.session())

        self.assertEqual(self.sync(client), 0)
        client.v1.checkout.sessions.retrieve.assert_not_called()

    def test_stripe_error_does_not_stop_the_sync(self):
        client = MagicMock()
        client.v1.checkout.sessions.retrieve.side_effect = stripe.APIConnectionError('sin red')

        self.assertEqual(self.sync(client), 0)


class LicenseStatusTests(TestCase):
    def test_active_license_expires_when_its_date_passes(self):
        tenant = Tenant.objects.create(subdominio='viejo', nombre='Viejo', plan_id='pro')
        today = timezone.localdate()
        license_ = Licencia.objects.create(
            restaurante=tenant,
            plan='pro',
            fecha_inicio=today - timedelta(days=40),
            fecha_vencimiento=today - timedelta(days=1),
        )

        self.assertEqual(license_.estado_actual, Licencia.Status.EXPIRED)
        self.assertIn(license_, Licencia.objects.vencidas())
        self.assertNotIn(license_, Licencia.objects.vigentes())


class LandingCorsTests(TestCase):
    def preflight(self, path, origin):
        return self.client.options(
            path,
            headers={'Origin': origin, 'Access-Control-Request-Method': 'POST'},
        )

    @override_settings(LANDING_URL='https://delismart.publicvm.com')
    def test_landing_reaches_checkout_only(self):
        origin = 'https://delismart.publicvm.com'
        self.assertIn('Access-Control-Allow-Origin', self.preflight(CHECKOUT_URL, origin).headers)
        self.assertNotIn('Access-Control-Allow-Origin', self.preflight('/api/v1/admin/metrics/', origin).headers)

    @override_settings(LANDING_URL='https://delismart.publicvm.com')
    def test_landing_reaches_login(self):
        response = self.preflight('/api/v1/admin/auth/login/', 'https://delismart.publicvm.com')
        self.assertIn('Access-Control-Allow-Origin', response.headers)

    def test_admin_origin_is_allowed(self):
        response = self.preflight('/api/v1/admin/metrics/', 'http://localhost:5173')
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), 'http://localhost:5173')


class TenantStatusTests(TestCase):
    def test_returns_active_tenant(self):
        Tenant.objects.create(subdominio='elsabrosito', nombre='El Sabrosito', plan_id='pro', estado=Tenant.Status.ACTIVE)
        response = self.client.get('/api/tenants/elsabrosito/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'subdomain': 'elsabrosito',
            'restaurant_name': 'El Sabrosito',
            'plan_id': 'pro',
            'status': 'activo',
        })

    def test_hides_unpaid_and_unknown_tenants(self):
        Tenant.objects.create(subdominio='pendiente', nombre='Sin pagar', plan_id='pro')
        self.assertEqual(self.client.get('/api/tenants/pendiente/status/').status_code, 404)
        self.assertEqual(self.client.get('/api/tenants/noexiste/status/').status_code, 404)
