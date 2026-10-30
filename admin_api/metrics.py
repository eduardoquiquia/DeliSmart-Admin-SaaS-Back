from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tenants.models import Licencia, PagoStripe, Tenant
from tenants.plans import PLANS, annual_amount, monthly_equivalent

from .licenses import LicenseSerializer
from .payments import PaymentSerializer
from .permissions import IsSuperuser
from .tenants import TenantSerializer, tenants_with_license

EXPIRING_WINDOW_DAYS = 7
RECENT_LIMIT = 5


def _soles(cents):
    return Decimal(cents) / 100


def _cancellation_rate(month_start):
    """Licencias canceladas este mes sobre las que estaban vigentes al empezarlo."""
    active_at_start = Licencia.objects.filter(
        Q(fecha_cancelacion__isnull=True) | Q(fecha_cancelacion__gte=month_start),
        fecha_inicio__lt=month_start,
        fecha_vencimiento__gte=month_start,
    ).count()
    cancelled = Licencia.objects.filter(fecha_cancelacion__gte=month_start).count()
    return round(cancelled * 100 / active_at_start, 1) if active_at_start else 0


class MetricsView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        current = Licencia.objects.vigentes().select_related('restaurante')
        expiring = current.filter(
            fecha_vencimiento__lte=today + timedelta(days=EXPIRING_WINDOW_DAYS),
        ).order_by('fecha_vencimiento')
        recent = (
            tenants_with_license().exclude(stripe_customer_id='').order_by('-fecha_creacion')[:RECENT_LIMIT]
        )
        payments = PagoStripe.objects.select_related('restaurante').order_by('-fecha_pago', '-id')[:RECENT_LIMIT]
        return Response({
            'restaurantes_activos': Tenant.objects.filter(estado=Tenant.Status.ACTIVE).count(),
            'mrr': _soles(sum(monthly_equivalent(item.plan, item.restaurante.billing_cycle) for item in current)),
            'nuevas_suscripciones_mes': Licencia.objects.filter(fecha_inicio__gte=month_start).count(),
            'ratio_cancelacion': _cancellation_rate(month_start),
            'ingresos_totales': PagoStripe.objects.aggregate(total=Sum('monto'))['total'] or Decimal('0.00'),
            # Los pedidos viven en el backend de restaurantes, que aún no expone este dato.
            'pedidos_globales': None,
            'licencias_por_vencer': LicenseSerializer(expiring, many=True).data,
            'ultimos_restaurantes': TenantSerializer(recent, many=True).data,
            'ultimos_pagos': PaymentSerializer(payments, many=True).data,
        })


class PlanListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([
            {
                'id': plan_id,
                'nombre': plan['name'],
                'precio_mensual': _soles(plan['monthly_amount']),
                'precio_anual': _soles(annual_amount(plan_id)),
            }
            for plan_id, plan in PLANS.items()
        ])
