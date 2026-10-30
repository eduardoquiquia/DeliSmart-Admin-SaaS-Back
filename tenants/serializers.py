from rest_framework import serializers

from .models import Tenant
from .plans import PLANS

RESERVED_SUBDOMAINS = {
    'admin', 'api', 'app', 'blog', 'cdn', 'dashboard', 'delismart', 'ftp', 'localhost', 'mail',
    'panel', 'smtp', 'soporte', 'static', 'status', 'support', 'tenants', 'ventas', 'www',
}


class CheckoutSessionSerializer(serializers.Serializer):
    plan_id = serializers.ChoiceField(choices=list(PLANS))
    billing_cycle = serializers.ChoiceField(choices=Tenant.BillingCycle, default=Tenant.BillingCycle.MONTHLY)
    restaurant_name = serializers.CharField(max_length=120)
    subdomain = serializers.RegexField(
        r'^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$',
        error_messages={'invalid': 'Usa de 3 a 63 letras minúsculas, números o guiones.'},
    )

    def validate_subdomain(self, value):
        if value in RESERVED_SUBDOMAINS:
            raise serializers.ValidationError('Este subdominio está reservado.')
        return value
