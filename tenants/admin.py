from django.contrib import admin

from .models import Tenant


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('subdomain', 'restaurant_name', 'plan_id', 'billing_cycle', 'status', 'created_at')
    list_filter = ('status', 'plan_id', 'billing_cycle')
    search_fields = ('subdomain', 'restaurant_name')
