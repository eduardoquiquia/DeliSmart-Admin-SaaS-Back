# DeliSmart Admin Backend

API de Django REST Framework para Stripe, los tenants y el panel de administración. Usa únicamente PostgreSQL en Neon: sin `DATABASE_URL` el proyecto no arranca.

## Puesta en marcha

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
cp .env.example .env
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py createsuperuser
.venv/Scripts/python manage.py runserver
```

Las pruebas corren sobre el mismo servidor PostgreSQL, en una base temporal `test_*`:

```bash
.venv/Scripts/python manage.py test
```

## Webhook de Stripe

El endpoint `/api/stripe/webhook/` debe recibir estos eventos:

- `checkout.session.completed`
- `checkout.session.async_payment_succeeded`
- `invoice.paid`
- `customer.subscription.deleted`

Si un webhook no llega, por ejemplo en local sin `stripe listen`, el panel consulta cada minuto `stripe/sync/`. Ese endpoint pregunta a Stripe por los checkouts pendientes y activa los pagados.

## API del panel

Todo cuelga de `/api/v1/admin/` y exige un JWT de superusuario, salvo `health/` y `auth/login/`.

| Ruta | Uso |
| --- | --- |
| `auth/login/`, `auth/refresh/`, `auth/me/` | Sesión |
| `metrics/` | KPIs globales |
| `tenants/` | CRUD, `search`, `estado`, `page` |
| `licenses/` | CRUD, `search`, `estado`, `page` |
| `payments/` | Historial, `search`, `page` |
| `stripe/sync/` | Activa checkouts pagados sin webhook |
| `plans/` | Catálogo de planes |
| `health/` | Estado del servidor |
