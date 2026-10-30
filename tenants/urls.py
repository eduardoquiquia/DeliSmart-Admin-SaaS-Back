from django.urls import path

from . import views

urlpatterns = [
    path('stripe/create-checkout-session/', views.CreateCheckoutSessionView.as_view()),
    path('stripe/webhook/', views.stripe_webhook),
]
