import re

from rest_framework import serializers

from .models import Tenant
from .plans import PLANS

RESERVED_SUBDOMAINS = {
    'admin', 'api', 'app', 'blog', 'cdn', 'dashboard', 'delismart', 'ftp', 'localhost', 'mail',
    'panel', 'smtp', 'soporte', 'static', 'status', 'support', 'tenants', 'ventas', 'www',
}


def check_subdomain(value):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', value):
        raise serializers.ValidationError('Usa de 3 a 63 letras minúsculas, números o guiones.')
    if value in RESERVED_SUBDOMAINS:
        raise serializers.ValidationError('Este subdominio está reservado.')
    return value


class CheckoutSessionSerializer(serializers.Serializer):
    plan_id = serializers.ChoiceField(choices=list(PLANS))
    billing_cycle = serializers.ChoiceField(choices=Tenant.BillingCycle, default=Tenant.BillingCycle.MONTHLY)
    restaurant_name = serializers.CharField(max_length=120, source='nombre')
    subdomain = serializers.CharField(source='subdominio')

    def validate_subdomain(self, value):
        return check_subdomain(value)


class TenantStatusSerializer(serializers.ModelSerializer):
    subdomain = serializers.CharField(source='subdominio')
    restaurant_name = serializers.CharField(source='nombre')
    status = serializers.CharField(source='estado')

    class Meta:
        model = Tenant
        fields = ('subdomain', 'restaurant_name', 'plan_id', 'status')
