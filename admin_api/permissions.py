from rest_framework.permissions import BasePermission

from tenants.models import Tenant


class IsSuperuser(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_superuser)


class IsTenantOwner(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and Tenant.objects.filter(owner=request.user).exists())
