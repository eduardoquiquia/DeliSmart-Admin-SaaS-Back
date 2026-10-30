from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .auth import HealthView, LoginView, ProfileView
from .licenses import LicenseViewSet
from .payments import PaymentListView
from .tenants import TenantViewSet

router = DefaultRouter()
router.register('tenants', TenantViewSet, basename='tenant')
router.register('licenses', LicenseViewSet, basename='license')

urlpatterns = [
    path('health/', HealthView.as_view()),
    path('auth/login/', LoginView.as_view()),
    path('auth/refresh/', TokenRefreshView.as_view()),
    path('auth/me/', ProfileView.as_view()),
    path('payments/', PaymentListView.as_view()),
    *router.urls,
]
