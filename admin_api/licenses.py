from django.db import transaction
from django.utils import timezone
from rest_framework import filters, serializers, viewsets

from tenants.models import Licencia, Tenant

from .pagination import AdminPagination
from .permissions import IsSuperuser


class LicenseSerializer(serializers.ModelSerializer):
    restaurante_nombre = serializers.CharField(source='restaurante.nombre', read_only=True)
    restaurante_subdominio = serializers.CharField(source='restaurante.subdominio', read_only=True)
    dias_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Licencia
        fields = (
            'id', 'restaurante', 'restaurante_nombre', 'restaurante_subdominio', 'plan',
            'fecha_inicio', 'fecha_vencimiento', 'dias_restantes', 'monto_pagado', 'estado',
            'fecha_cancelacion', 'stripe_subscription_id',
        )
        read_only_fields = ('fecha_cancelacion', 'stripe_subscription_id')

    def get_dias_restantes(self, license_):
        return (license_.fecha_vencimiento - timezone.localdate()).days

    def to_representation(self, license_):
        data = super().to_representation(license_)
        data['estado'] = license_.estado_actual
        return data

    def validate(self, attrs):
        start = attrs.get('fecha_inicio', getattr(self.instance, 'fecha_inicio', None))
        end = attrs.get('fecha_vencimiento', getattr(self.instance, 'fecha_vencimiento', None))
        if start and end and end < start:
            raise serializers.ValidationError({'fecha_vencimiento': 'No puede ser anterior a la fecha de inicio.'})
        return attrs


class LicenseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperuser]
    serializer_class = LicenseSerializer
    pagination_class = AdminPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['restaurante__subdominio', 'restaurante__nombre']

    def get_queryset(self):
        queryset = Licencia.objects.select_related('restaurante').order_by('fecha_vencimiento', 'id')
        estado = self.request.query_params.get('estado')
        if estado == Licencia.Status.ACTIVE:
            return queryset.vigentes()
        if estado == Licencia.Status.EXPIRED:
            return queryset.vencidas()
        return queryset.filter(estado=estado) if estado else queryset

    def perform_create(self, serializer):
        self._save(serializer)

    def perform_update(self, serializer):
        self._save(serializer)

    @transaction.atomic
    def _save(self, serializer):
        # El landing lee el plan del tenant: debe coincidir con el de su licencia.
        license_ = serializer.save()
        Tenant.objects.filter(pk=license_.restaurante_id).update(plan_id=license_.plan)
