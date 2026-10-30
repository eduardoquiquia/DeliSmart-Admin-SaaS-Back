import logging

import stripe
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .serializers import CheckoutSessionSerializer
from .services import SubdomainTaken, provision_tenant, start_checkout

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
        except stripe.StripeError:
            logger.exception('No se pudo crear la sesión de Stripe')
            return Response(
                {'detail': 'No pudimos iniciar el pago. Inténtalo de nuevo.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'checkout_url': session.url}, status=status.HTTP_201_CREATED)


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

    if event.type == 'checkout.session.completed':
        provision_tenant(event.data.object)
    return HttpResponse(status=200)
