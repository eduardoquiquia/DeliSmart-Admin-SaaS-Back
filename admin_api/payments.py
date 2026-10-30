from rest_framework import filters, generics, serializers

from tenants.models import PagoStripe

from .pagination import AdminPagination
from .permissions import IsSuperuser


class PaymentSerializer(serializers.ModelSerializer):
    restaurante_nombre = serializers.CharField(source='restaurante.nombre')
    restaurante_subdominio = serializers.CharField(source='restaurante.subdominio')

    class Meta:
        model = PagoStripe
        fields = (
            'id', 'restaurante', 'restaurante_nombre', 'restaurante_subdominio',
            'stripe_checkout_id', 'monto', 'moneda', 'fecha_pago',
        )


class PaymentListView(generics.ListAPIView):
    permission_classes = [IsSuperuser]
    serializer_class = PaymentSerializer
    pagination_class = AdminPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['restaurante__subdominio', 'restaurante__nombre', 'stripe_checkout_id']
    queryset = PagoStripe.objects.select_related('restaurante').order_by('-fecha_pago', '-id')
