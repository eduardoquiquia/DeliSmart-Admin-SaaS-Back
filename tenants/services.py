import calendar
import logging
import secrets
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import stripe
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Licencia, PagoStripe, Tenant
from .plans import stripe_price_data

logger = logging.getLogger(__name__)

# Stripe expira una sesión de checkout sin pagar a las 24 horas.
CHECKOUT_LIFETIME = timedelta(hours=25)


class SubdomainTaken(Exception):
    pass


def get_stripe_client():
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY)


def start_checkout(data):
    """Reserva el subdominio y devuelve la sesión de Stripe que lo pagará."""
    client = get_stripe_client()
    tenant = _reserve_subdomain(client, data)
    metadata = {
        'subdomain': tenant.subdominio,
        'restaurant_name': tenant.nombre,
        'plan_id': tenant.plan_id,
    }
    try:
        session = client.v1.checkout.sessions.create(params={
            'mode': 'subscription',
            'locale': 'es',
            'line_items': [{
                'quantity': 1,
                'price_data': stripe_price_data(tenant.plan_id, tenant.billing_cycle),
            }],
            'metadata': metadata,
            'subscription_data': {'metadata': metadata},
            'success_url': f'{settings.LANDING_URL}/checkout/exito?subdomain={tenant.subdominio}',
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
        tenant = Tenant.objects.select_for_update().filter(subdominio=data['subdominio']).first()
        if tenant is None:
            try:
                with transaction.atomic():
                    return Tenant.objects.create(**data)
            except IntegrityError as exc:
                raise SubdomainTaken from exc

        if tenant.estado != Tenant.Status.PENDING or not tenant.stripe_session_id:
            raise SubdomainTaken

        previous = client.v1.checkout.sessions.retrieve(tenant.stripe_session_id)
        if previous.status == 'complete':
            raise SubdomainTaken
        if previous.status == 'open':
            client.v1.checkout.sessions.expire(tenant.stripe_session_id)

        tenant.nombre = data['nombre']
        tenant.plan_id = data['plan_id']
        tenant.billing_cycle = data['billing_cycle']
        tenant.stripe_session_id = ''
        tenant.save()
        return tenant


def _add_months(start, months):
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def _soles(cents):
    return Decimal(cents) / 100


@transaction.atomic
def provision_tenant(session):
    """Activa el tenant de una sesión pagada. Stripe puede repetir el evento."""
    # Los métodos de pago diferidos completan el checkout antes de cobrar.
    if session.payment_status == 'unpaid':
        return

    tenant = (
        Tenant.objects.select_for_update()
        .filter(subdominio=session.metadata.subdomain, stripe_session_id=session.id)
        .first()
    )
    if tenant is None:
        logger.error('Pago sin tenant reservado: sesión %s', session.id)
        return
    if tenant.estado != Tenant.Status.PENDING:
        return

    email = session.customer_details.email
    password = secrets.token_urlsafe(12)
    tenant.owner = get_user_model().objects.create_user(
        username=tenant.subdominio,
        email=email,
        password=password,
    )
    tenant.estado = Tenant.Status.ACTIVE
    tenant.email_admin = email
    tenant.telefono = session.customer_details.phone or ''
    tenant.stripe_customer_id = session.customer or ''
    tenant.save()

    today = timezone.localdate()
    months = 12 if tenant.billing_cycle == Tenant.BillingCycle.ANNUAL else 1
    amount = _soles(session.amount_total)
    Licencia.objects.create(
        restaurante=tenant,
        plan=tenant.plan_id,
        fecha_inicio=today,
        fecha_vencimiento=_add_months(today, months),
        monto_pagado=amount,
        stripe_subscription_id=session.subscription or '',
    )
    PagoStripe.objects.create(
        restaurante=tenant,
        stripe_checkout_id=session.id,
        monto=amount,
        moneda=session.currency,
        raw_payload=session.to_dict(),
    )

    # Si el correo falla se revierte todo y Stripe reintenta: la contraseña no se guarda en claro.
    send_mail(
        subject=f'Tu acceso a DeliSmart: {tenant.nombre}',
        message=(
            f'Tu restaurante ya está activo en https://{tenant.subdominio}.{settings.ROOT_DOMAIN}\n\n'
            f'Usuario: {tenant.subdominio}\n'
            f'Contraseña temporal: {password}\n'
        ),
        from_email=None,
        recipient_list=[email],
    )
    return True


def sync_pending_checkouts():
    """Activa los checkouts pagados cuyo webhook no llegó. Devuelve cuántos activó."""
    pending = Tenant.objects.filter(
        estado=Tenant.Status.PENDING,
        updated_at__gte=timezone.now() - CHECKOUT_LIFETIME,
    ).exclude(stripe_session_id='')

    activated = 0
    client = get_stripe_client()
    for tenant in pending:
        try:
            session = client.v1.checkout.sessions.retrieve(tenant.stripe_session_id)
        except stripe.StripeError:
            logger.exception('No se pudo consultar la sesión %s', tenant.stripe_session_id)
            continue
        if session.status == 'complete' and provision_tenant(session):
            activated += 1
    return activated


def _invoice_subscription_id(invoice):
    # La API de Stripe movió este campo a `parent`; las cuentas antiguas siguen enviando el anterior.
    data = invoice.to_dict()
    details = (data.get('parent') or {}).get('subscription_details') or {}
    return details.get('subscription') or data.get('subscription')


@transaction.atomic
def renew_license(invoice):
    """Registra el cobro de una renovación y extiende la licencia. Stripe puede repetir el evento."""
    # El primer cobro ya entra por checkout.session.completed.
    if invoice.billing_reason == 'subscription_create':
        return

    subscription_id = _invoice_subscription_id(invoice)
    license_ = (
        Licencia.objects.select_for_update().filter(stripe_subscription_id=subscription_id).first()
        if subscription_id
        else None
    )
    if license_ is None:
        logger.error('Factura sin licencia: %s', invoice.id)
        return

    amount = _soles(invoice.amount_paid)
    _, created = PagoStripe.objects.get_or_create(
        stripe_checkout_id=invoice.id,
        defaults={
            'restaurante_id': license_.restaurante_id,
            'monto': amount,
            'moneda': invoice.currency,
            'raw_payload': invoice.to_dict(),
        },
    )
    if not created:
        return

    period_end = max(line.period.end for line in invoice.lines.data)
    license_.fecha_vencimiento = timezone.localdate(datetime.fromtimestamp(period_end, tz=UTC))
    license_.monto_pagado += amount
    license_.estado = Licencia.Status.ACTIVE
    license_.save()


@transaction.atomic
def cancel_subscription(subscription):
    """Stripe da por terminada la suscripción: se cancela la licencia y se corta el acceso."""
    license_ = (
        Licencia.objects.select_for_update().filter(stripe_subscription_id=subscription.id).first()
    )
    if license_ is None:
        return
    license_.estado = Licencia.Status.CANCELLED
    license_.save()
    Tenant.objects.filter(pk=license_.restaurante_id).update(estado=Tenant.Status.SUSPENDED)
