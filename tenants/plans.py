"""Catálogo de planes. Los montos están en céntimos de sol y solo se calculan aquí."""

ANNUAL_DISCOUNT_PERCENT = 20

PLANS = {
    'expreso': {'name': 'Expreso', 'monthly_amount': 10300},
    'pro': {'name': 'Pro Restaurante', 'monthly_amount': 19900},
    'cadenas': {'name': 'Cadenas', 'monthly_amount': 39900},
}


def stripe_price_data(plan_id, billing_cycle):
    plan = PLANS[plan_id]
    if billing_cycle == 'annual':
        unit_amount = plan['monthly_amount'] * 12 * (100 - ANNUAL_DISCOUNT_PERCENT) // 100
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
