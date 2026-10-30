from django.urls import path

from . import views

urlpatterns = [
    path('stripe/create-checkout-session/', views.CreateCheckoutSessionView.as_view()),
    path('stripe/complete-checkout/', views.CompleteCheckoutView.as_view()),
    path('stripe/webhook/', views.stripe_webhook),
    path('tenants/<str:subdomain>/status/', views.TenantStatusView.as_view()),
]
