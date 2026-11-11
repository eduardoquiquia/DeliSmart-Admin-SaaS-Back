from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import PagoStripe, Tenant
from tenants.restaurant_link import SSONotConfigured, restaurant_sso_url

from .licenses import LicenseSerializer
from .payments import PaymentSerializer
from .permissions import IsTenantOwner

PAYMENT_LIMIT = 10


class MyRestaurantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ('nombre', 'subdominio', 'ruc', 'telefono', 'email_admin', 'estado', 'plan_id', 'billing_cycle')


class MyPlanView(APIView):
    permission_classes = [IsTenantOwner]

    def get(self, request):
        tenant = Tenant.objects.get(owner=request.user)
        license_ = tenant.licencias.select_related('restaurante').order_by('-fecha_inicio', '-id').first()
        payments = PagoStripe.objects.select_related('restaurante').filter(restaurante=tenant)
        return Response({
            'restaurante': MyRestaurantSerializer(tenant).data,
            'licencia': LicenseSerializer(license_).data if license_ else None,
            'pagos': PaymentSerializer(payments.order_by('-fecha_pago', '-id')[:PAYMENT_LIMIT], many=True).data,
        })


class RestaurantAccessView(APIView):
    """Enlace de un solo uso para entrar al panel de la pollería con la sesión ya iniciada."""

    permission_classes = [IsTenantOwner]

    def post(self, request):
        tenant = Tenant.objects.get(owner=request.user)
        try:
            url = restaurant_sso_url(tenant, request.user)
        except SSONotConfigured:
            return Response(
                {'detail': 'El acceso al panel de la pollería aún no está configurado.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'url': url})
