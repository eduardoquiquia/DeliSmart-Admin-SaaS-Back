import logging

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken

from .models import Tenant
from .serializers import CheckoutSessionSerializer, CompleteCheckoutSerializer, TenantStatusSerializer
from .services import (
    CheckoutLoginUsed,
    CheckoutNotPaid,
    EmailTaken,
    SubdomainTaken,
    cancel_subscription,
    complete_checkout,
    provision_tenant,
    renew_license,
    start_checkout,
)

logger = logging.getLogger(__name__)


class CreateCheckoutSessionView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = CheckoutSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = start_checkout(serializer.validated_data)
        except SubdomainTaken:
            return Response(
                {'subdomain': ['Este subdominio ya está en uso.']},
                status=status.HTTP_409_CONFLICT,
            )
        except EmailTaken:
            return Response(
                {'email': ['Este correo ya tiene una cuenta. Inicia sesión para continuar.']},
                status=status.HTTP_409_CONFLICT,
            )
        except stripe.StripeError:
            logger.exception('No se pudo crear la sesión de Stripe')
            return Response(
                {'detail': 'No pudimos iniciar el pago. Inténtalo de nuevo.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'checkout_url': session.url}, status=status.HTTP_201_CREATED)


class CompleteCheckoutView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AnonRateThrottle]

    def post(self, request):
        serializer = CompleteCheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            owner = complete_checkout(serializer.validated_data['session_id'])
        except Tenant.DoesNotExist:
            return Response({'detail': 'No encontramos esta compra.'}, status=status.HTTP_404_NOT_FOUND)
        except CheckoutNotPaid:
            return Response({'detail': 'El pago aún se está confirmando.'}, status=status.HTTP_202_ACCEPTED)
        except CheckoutLoginUsed:
            return Response({'detail': 'Esta compra ya inició sesión.'}, status=status.HTTP_410_GONE)
        except stripe.StripeError:
            logger.exception('No se pudo confirmar la sesión de Stripe')
            return Response(
                {'detail': 'No pudimos confirmar el pago. Inténtalo de nuevo.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        refresh = RefreshToken.for_user(owner)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})


class TenantStatusView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, subdomain):
        tenant = get_object_or_404(Tenant.objects.exclude(estado=Tenant.Status.PENDING), subdominio=subdomain)
        return Response(TenantStatusSerializer(tenant).data)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error('STRIPE_WEBHOOK_SECRET no está configurado')
        return HttpResponse(status=503)

    try:
        event = stripe.Webhook.construct_event(
            request.body,
            request.headers.get('Stripe-Signature'),
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)

    if event.type in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        provision_tenant(event.data.object)
    elif event.type == 'invoice.paid':
        renew_license(event.data.object)
    elif event.type == 'customer.subscription.deleted':
        cancel_subscription(event.data.object)
    return HttpResponse(status=200)
