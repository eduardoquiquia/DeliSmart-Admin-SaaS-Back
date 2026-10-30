from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .plans import PLAN_CHOICES


class Tenant(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pendiente', 'Pendiente de pago'
        ACTIVE = 'activo', 'Activo'
        SUSPENDED = 'suspendido', 'Suspendido'

    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Mensual'
        ANNUAL = 'annual', 'Anual'

    nombre = models.CharField(max_length=120)
    subdominio = models.CharField(max_length=63, unique=True)
    ruc = models.CharField(max_length=11, blank=True)
    telefono = models.CharField(max_length=30, blank=True)
    email_admin = models.EmailField(blank=True)
    plan_id = models.CharField(max_length=20, choices=PLAN_CHOICES)
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle, default=BillingCycle.MONTHLY)
    estado = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant',
    )
    stripe_session_id = models.CharField(max_length=255, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    login_issued_at = models.DateTimeField(null=True, blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.nombre} ({self.subdominio})'


class LicenciaQuerySet(models.QuerySet):
    def vigentes(self):
        return self.filter(estado=Licencia.Status.ACTIVE, fecha_vencimiento__gte=timezone.localdate())

    def vencidas(self):
        return self.filter(
            Q(estado=Licencia.Status.EXPIRED)
            | Q(estado=Licencia.Status.ACTIVE, fecha_vencimiento__lt=timezone.localdate())
        )


class Licencia(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'activa', 'Activa'
        EXPIRED = 'vencida', 'Vencida'
        CANCELLED = 'cancelada', 'Cancelada'

    restaurante = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='licencias')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    fecha_inicio = models.DateField()
    fecha_vencimiento = models.DateField()
    monto_pagado = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=10, choices=Status, default=Status.ACTIVE)
    fecha_cancelacion = models.DateField(null=True, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, db_index=True)

    objects = LicenciaQuerySet.as_manager()

    class Meta:
        verbose_name_plural = 'licencias'

    def __str__(self):
        return f'{self.restaurante.subdominio}: {self.plan}'

    def save(self, *args, **kwargs):
        if self.estado != self.Status.CANCELLED:
            self.fecha_cancelacion = None
        elif self.fecha_cancelacion is None:
            self.fecha_cancelacion = timezone.localdate()
        super().save(*args, **kwargs)

    @property
    def estado_actual(self):
        """Una licencia activa vence sola al pasar su fecha, sin depender de una tarea programada."""
        if self.estado == self.Status.ACTIVE and self.fecha_vencimiento < timezone.localdate():
            return self.Status.EXPIRED
        return self.estado


class PagoStripe(models.Model):
    # El historial de cobros no se pierde al borrar un restaurante.
    restaurante = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name='pagos')
    # Id de la sesión de checkout, o de la factura en las renovaciones.
    stripe_checkout_id = models.CharField(max_length=255, unique=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.CharField(max_length=3)
    fecha_pago = models.DateTimeField(default=timezone.now)
    raw_payload = models.JSONField()

    class Meta:
        verbose_name_plural = 'pagos de Stripe'

    def __str__(self):
        return self.stripe_checkout_id
