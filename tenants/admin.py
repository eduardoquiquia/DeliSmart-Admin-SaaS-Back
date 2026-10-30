from django.contrib import admin

from .models import Licencia, PagoStripe, Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('subdominio', 'nombre', 'plan_id', 'billing_cycle', 'estado', 'fecha_creacion')
    list_filter = ('estado', 'plan_id', 'billing_cycle')
    search_fields = ('subdominio', 'nombre')


@admin.register(Licencia)
class LicenciaAdmin(admin.ModelAdmin):
    list_display = ('restaurante', 'plan', 'fecha_inicio', 'fecha_vencimiento', 'estado')
    list_filter = ('estado', 'plan')
    search_fields = ('restaurante__subdominio', 'restaurante__nombre')


@admin.register(PagoStripe)
class PagoStripeAdmin(admin.ModelAdmin):
    list_display = ('stripe_checkout_id', 'restaurante', 'monto', 'moneda', 'fecha_pago')
    search_fields = ('stripe_checkout_id', 'restaurante__subdominio')
