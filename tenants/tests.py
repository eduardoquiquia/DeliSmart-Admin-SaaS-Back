import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import stripe
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from .models import Tenant
from .plans import stripe_price_data

CHECKOUT_URL = '/api/stripe/create-checkout-session/'
WEBHOOK_URL = '/api/stripe/webhook/'
WEBHOOK_SECRET = 'whsec_unit_test'


def checkout_payload(**overrides):
    return {
        'plan_id': 'pro',
        'billing_cycle': 'monthly',
        'restaurant_name': 'El Sabrosito',
        'subdomain': 'elsabrosito',
        **overrides,
    }


def stripe_client(session_id='cs_new'):
    client = MagicMock()
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
        tenant = Tenant.objects.get(subdomain='elsabrosito')
        self.assertEqual(tenant.status, Tenant.Status.PENDING)
        self.assertEqual(tenant.stripe_session_id, 'cs_new')

    def test_rejects_invalid_and_reserved_subdomains(self):
        for subdomain in ('Mi_Local', 'ab', '-abc', 'www'):
            with self.subTest(subdomain=subdomain):
                self.assertEqual(self.post(stripe_client(), subdomain=subdomain).status_code, 400)

    def test_rejects_unknown_plan(self):
        self.assertEqual(self.post(stripe_client(), plan_id='gratis').status_code, 400)

    def test_rejects_active_subdomain(self):
        Tenant.objects.create(subdomain='elsabrosito', restaurant_name='Otro', plan_id='pro', status=Tenant.Status.ACTIVE)
        client = stripe_client()
        self.assertEqual(self.post(client).status_code, 409)
        client.v1.checkout.sessions.create.assert_not_called()

    def test_new_checkout_expires_previous_unpaid_one(self):
        Tenant.objects.create(subdomain='elsabrosito', restaurant_name='Otro', plan_id='expreso', stripe_session_id='cs_old')
        client = stripe_client()
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='open')

        self.assertEqual(self.post(client).status_code, 201)

        client.v1.checkout.sessions.expire.assert_called_once_with('cs_old')
        tenant = Tenant.objects.get(subdomain='elsabrosito')
        self.assertEqual((tenant.stripe_session_id, tenant.plan_id), ('cs_new', 'pro'))

    def test_rejects_subdomain_paid_while_webhook_is_in_flight(self):
        Tenant.objects.create(subdomain='elsabrosito', restaurant_name='Otro', plan_id='pro', stripe_session_id='cs_old')
        client = stripe_client()
        client.v1.checkout.sessions.retrieve.return_value = SimpleNamespace(status='complete')

        self.assertEqual(self.post(client).status_code, 409)
        client.v1.checkout.sessions.create.assert_not_called()

    def test_stripe_failure_releases_subdomain(self):
        client = stripe_client()
        client.v1.checkout.sessions.create.side_effect = stripe.APIConnectionError('sin red')

        self.assertEqual(self.post(client).status_code, 502)
        self.assertFalse(Tenant.objects.filter(subdomain='elsabrosito').exists())


@override_settings(STRIPE_WEBHOOK_SECRET=WEBHOOK_SECRET)
class StripeWebhookTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            subdomain='elsabrosito',
            restaurant_name='El Sabrosito',
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
                'customer_details': {'email': 'dueno@example.com'},
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
        self.assertEqual(self.tenant.status, Tenant.Status.PENDING)

    @override_settings(STRIPE_WEBHOOK_SECRET='')
    def test_refuses_events_without_configured_secret(self):
        self.assertEqual(self.post(self.event_body(), secret='').status_code, 503)

    def test_activates_tenant_and_creates_credentials(self):
        self.assertEqual(self.post(self.event_body()).status_code, 200)

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)
        self.assertEqual(self.tenant.stripe_subscription_id, 'sub_1')
        owner = self.tenant.owner
        self.assertEqual((owner.username, owner.email), ('elsabrosito', 'dueno@example.com'))
        self.assertEqual(len(mail.outbox), 1)
        password = mail.outbox[0].body.split('Contraseña temporal: ')[1].strip()
        self.assertTrue(owner.check_password(password))

    def test_waits_for_deferred_payment_before_activating(self):
        self.post(self.event_body(payment_status='unpaid'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.PENDING)

        self.post(self.event_body(event_type='checkout.session.async_payment_succeeded'))
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.ACTIVE)

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
        self.assertEqual(self.tenant.status, Tenant.Status.PENDING)
        self.assertEqual(get_user_model().objects.count(), 0)

    def test_ignores_session_replaced_by_newer_checkout(self):
        self.assertEqual(self.post(self.event_body(session_id='cs_other')).status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.PENDING)

    def test_ignores_other_events(self):
        self.assertEqual(self.post(self.event_body(event_type='invoice.paid')).status_code, 200)
        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.status, Tenant.Status.PENDING)


class TenantStatusTests(TestCase):
    def test_returns_active_tenant(self):
        Tenant.objects.create(subdomain='elsabrosito', restaurant_name='El Sabrosito', plan_id='pro', status=Tenant.Status.ACTIVE)
        response = self.client.get('/api/tenants/elsabrosito/status/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'subdomain': 'elsabrosito',
            'restaurant_name': 'El Sabrosito',
            'plan_id': 'pro',
            'status': 'activo',
        })

    def test_hides_unpaid_and_unknown_tenants(self):
        Tenant.objects.create(subdomain='pendiente', restaurant_name='Sin pagar', plan_id='pro')
        self.assertEqual(self.client.get('/api/tenants/pendiente/status/').status_code, 404)
        self.assertEqual(self.client.get('/api/tenants/noexiste/status/').status_code, 404)
