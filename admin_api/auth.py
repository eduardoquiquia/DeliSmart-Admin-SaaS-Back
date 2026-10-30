from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from .permissions import IsSuperuser


class SuperuserTokenSerializer(TokenObtainPairSerializer):
    default_error_messages = {'no_active_account': 'Usuario o contraseña incorrectos.'}

    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_superuser:
            raise AuthenticationFailed('Esta cuenta no tiene acceso al panel.')
        return data


class LoginView(TokenObtainPairView):
    serializer_class = SuperuserTokenSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'admin_login'


class ProfileView(APIView):
    permission_classes = [IsSuperuser]

    def get(self, request):
        user = request.user
        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'nombre': user.get_full_name() or user.username,
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
