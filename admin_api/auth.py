from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from tenants.models import Tenant


class PanelTokenSerializer(TokenObtainPairSerializer):
    default_error_messages = {'no_active_account': 'Correo o contraseña incorrectos.'}

    def validate(self, attrs):
        # Los dueños entran con su correo; un superusuario, con cualquiera de los dos.
        identifier = attrs[self.username_field]
        user = get_user_model().objects.filter(email__iexact=identifier).first()
        if user is not None:
            attrs[self.username_field] = user.get_username()

        data = super().validate(attrs)
        if not self.user.is_superuser and not Tenant.objects.filter(owner=self.user).exists():
            raise AuthenticationFailed('Esta cuenta no tiene acceso al panel.')
        return data


class LoginView(TokenObtainPairView):
    serializer_class = PanelTokenSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'admin_login'


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'nombre': user.get_full_name() or user.username,
            'rol': 'superusuario' if user.is_superuser else 'cliente',
        })


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except DatabaseError:
            return Response({'status': 'caido'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({'status': 'ok'})
