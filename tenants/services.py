import stripe
from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Tenant
from .plans import stripe_price_data


class SubdomainTaken(Exception):
    pass


def get_stripe_client():
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


def start_checkout(data):
    """Reserva el subdominio y devuelve la sesión de Stripe que lo pagará."""
    client = get_stripe_client()
    tenant = _reserve_subdomain(client, data)
    metadata = {
        'subdomain': tenant.subdomain,
        'restaurant_name': tenant.restaurant_name,
        'plan_id': tenant.plan_id,
    }
    try:
        session = client.v1.checkout.sessions.create(params={
            'mode': 'subscription',
            'payment_method_types': ['card'],
            'locale': 'es',
            'line_items': [{
                'quantity': 1,
                'price_data': stripe_price_data(tenant.plan_id, tenant.billing_cycle),
            }],
            'metadata': metadata,
            'subscription_data': {'metadata': metadata},
            'success_url': f'{settings.LANDING_URL}/checkout/exito?subdomain={tenant.subdomain}',
            'cancel_url': f'{settings.LANDING_URL}/#planes',
        })
    except stripe.StripeError:
        tenant.delete()
        raise
    tenant.stripe_session_id = session.id
    tenant.save(update_fields=['stripe_session_id', 'updated_at'])
    return session


def _reserve_subdomain(client, data):
    """
    Un subdominio sin pagar no bloquea a nadie: el último checkout invalida al
    anterior en Stripe, así dos personas nunca pagan por el mismo subdominio.
    """
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().filter(subdomain=data['subdomain']).first()
        if tenant is None:
            try:
                with transaction.atomic():
                    return Tenant.objects.create(**data)
            except IntegrityError as exc:
                raise SubdomainTaken from exc

        if tenant.status != Tenant.Status.PENDING or not tenant.stripe_session_id:
            raise SubdomainTaken

        previous = client.v1.checkout.sessions.retrieve(tenant.stripe_session_id)
        if previous.status == 'complete':
            raise SubdomainTaken
        if previous.status == 'open':
            client.v1.checkout.sessions.expire(tenant.stripe_session_id)

        tenant.restaurant_name = data['restaurant_name']
        tenant.plan_id = data['plan_id']
        tenant.billing_cycle = data['billing_cycle']
        tenant.stripe_session_id = ''
        tenant.save()
        return tenant
