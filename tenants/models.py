from django.conf import settings
from django.db import models


class Tenant(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pendiente', 'Pendiente de pago'
        ACTIVE = 'activo', 'Activo'
        SUSPENDED = 'suspendido', 'Suspendido'

    class BillingCycle(models.TextChoices):
        MONTHLY = 'monthly', 'Mensual'
        ANNUAL = 'annual', 'Anual'

    subdomain = models.CharField(max_length=63, unique=True)
    restaurant_name = models.CharField(max_length=120)
    plan_id = models.CharField(max_length=20)
    billing_cycle = models.CharField(max_length=10, choices=BillingCycle, default=BillingCycle.MONTHLY)
    status = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tenant',
    )
    stripe_session_id = models.CharField(max_length=255, blank=True)
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.restaurant_name} ({self.subdomain})'
