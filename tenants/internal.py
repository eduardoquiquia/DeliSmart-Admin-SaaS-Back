import hmac

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Tenant
from .restaurant_link import license_state


class InternalTokenView(APIView):
    """Solo para restaurant-back: exige `Authorization: Bearer <INTERNAL_API_TOKEN>`."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        expected = settings.INTERNAL_API_TOKEN
        received = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
        if not expected or not hmac.compare_digest(received, expected):
            raise AuthenticationFailed('Token interno inválido.')


class LicenseBySubdomainView(InternalTokenView):
    def get(self, request, subdominio):
        tenant = get_object_or_404(Tenant, subdominio=subdominio.lower())
        return Response(license_state(tenant))
