import logging

import stripe
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .serializers import CheckoutSessionSerializer
from .services import SubdomainTaken, start_checkout

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
