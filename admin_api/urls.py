from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .auth import HealthView, LoginView, ProfileView

urlpatterns = [
    path('health/', HealthView.as_view()),
    path('auth/login/', LoginView.as_view()),
    path('auth/refresh/', TokenRefreshView.as_view()),
    path('auth/me/', ProfileView.as_view()),
]
