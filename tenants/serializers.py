import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
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
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=150, source='email_admin')
    phone = serializers.CharField(max_length=30, source='telefono')
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    restaurant_name = serializers.CharField(max_length=120, source='nombre')
    ruc = serializers.RegexField(
        r'^\d{11}$',
        required=False,
        allow_blank=True,
        error_messages={'invalid': 'El RUC tiene 11 dígitos.'},
    )
    subdomain = serializers.CharField(source='subdominio')

    def validate_email(self, value):
        return value.lower()

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate_subdomain(self, value):
        return check_subdomain(value)


class CompleteCheckoutSerializer(serializers.Serializer):
    session_id = serializers.CharField(max_length=255)


class TenantStatusSerializer(serializers.ModelSerializer):
    subdomain = serializers.CharField(source='subdominio')
    restaurant_name = serializers.CharField(source='nombre')
    status = serializers.CharField(source='estado')

    class Meta:
        model = Tenant
        fields = ('subdomain', 'restaurant_name', 'plan_id', 'status')
