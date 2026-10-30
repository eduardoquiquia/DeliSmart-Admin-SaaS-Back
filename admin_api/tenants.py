from django.db.models import Prefetch, ProtectedError
from rest_framework import filters, serializers, status, viewsets
from rest_framework.response import Response

from tenants.models import Licencia, Tenant
from tenants.serializers import check_subdomain

from .pagination import AdminPagination
from .permissions import IsSuperuser


class TenantSerializer(serializers.ModelSerializer):
    licencia = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = (
            'id', 'nombre', 'subdominio', 'ruc', 'telefono', 'email_admin', 'fecha_creacion',
            'estado', 'plan_id', 'billing_cycle', 'licencia',
        )
        read_only_fields = ('fecha_creacion',)

    def get_licencia(self, tenant):
        # `licencias` llega precargada de la más reciente a la más antigua.
        current = next(iter(tenant.licencias.all()), None)
        if current is None:
            return None
        return {
            'id': current.id,
            'plan': current.plan,
            'estado': current.estado_actual,
            'fecha_vencimiento': current.fecha_vencimiento,
        }

    def validate_subdominio(self, value):
        pending = self.instance is not None and self.instance.estado == Tenant.Status.PENDING
        if pending and value != self.instance.subdominio:
            raise serializers.ValidationError('El subdominio está reservado para un pago en curso.')
        return check_subdomain(value)

    def validate_estado(self, value):
        current = self.instance.estado if self.instance else None
        if value == Tenant.Status.PENDING and current != Tenant.Status.PENDING:
            raise serializers.ValidationError('Solo un checkout en curso deja un restaurante pendiente.')
        if current == Tenant.Status.PENDING and value != Tenant.Status.PENDING:
            raise serializers.ValidationError('Este restaurante se activa cuando Stripe confirma el pago.')
        return value

    def create(self, validated_data):
        validated_data.setdefault('estado', Tenant.Status.ACTIVE)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # El plan vigente vive en la licencia; se cambia desde /licenses/.
        validated_data.pop('plan_id', None)
        validated_data.pop('billing_cycle', None)
        return super().update(instance, validated_data)


def tenants_with_license():
    latest_first = Licencia.objects.order_by('-fecha_inicio', '-id')
    return Tenant.objects.prefetch_related(Prefetch('licencias', queryset=latest_first))


class TenantViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperuser]
    serializer_class = TenantSerializer
    pagination_class = AdminPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['subdominio', 'nombre']

    def get_queryset(self):
        queryset = tenants_with_license().order_by('-fecha_creacion', '-id')
        estado = self.request.query_params.get('estado')
        return queryset.filter(estado=estado) if estado else queryset

    def destroy(self, request, *args, **kwargs):
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {'detail': 'Este restaurante tiene pagos registrados: suspéndelo en lugar de eliminarlo.'},
                status=status.HTTP_409_CONFLICT,
            )
