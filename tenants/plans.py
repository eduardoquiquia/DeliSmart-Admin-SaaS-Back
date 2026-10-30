"""Catálogo de planes. Los montos están en céntimos de sol y solo se calculan aquí."""

ANNUAL_DISCOUNT_PERCENT = 20

PLANS = {
    'expreso': {'name': 'Expreso', 'monthly_amount': 10300},
    'pro': {'name': 'Pro Restaurante', 'monthly_amount': 19900},
    'cadenas': {'name': 'Cadenas', 'monthly_amount': 39900},
}

PLAN_CHOICES = [(plan_id, plan['name']) for plan_id, plan in PLANS.items()]


def annual_amount(plan_id):
    return PLANS[plan_id]['monthly_amount'] * 12 * (100 - ANNUAL_DISCOUNT_PERCENT) // 100


def monthly_equivalent(plan_id, billing_cycle):
    """Lo que una suscripción aporta al MRR."""
    if billing_cycle == 'annual':
        return annual_amount(plan_id) // 12
    return PLANS[plan_id]['monthly_amount']


def stripe_price_data(plan_id, billing_cycle):
    plan = PLANS[plan_id]
    if billing_cycle == 'annual':
        unit_amount = annual_amount(plan_id)
        interval = 'year'
    else:
        unit_amount = plan['monthly_amount']
        interval = 'month'
    return {
        'currency': 'pen',
        'unit_amount': unit_amount,
        'recurring': {'interval': interval},
        'product_data': {'name': f"DeliSmart {plan['name']}"},
    }
