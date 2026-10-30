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

Si un webhook no llega, por ejemplo en local sin `stripe listen`, hay dos respaldos que preguntan a Stripe por el pago. Al volver del checkout, el landing llama a `POST /api/stripe/complete-checkout/`, que activa la cuenta y entrega los tokens una sola vez. Además, el panel de un superusuario consulta cada minuto `stripe/sync/`.

## Registro y acceso

`POST /api/stripe/create-checkout-session/` recibe los datos del dueño y del restaurante. Crea el usuario inactivo, el tenant pendiente y el cliente de Stripe, y los enlaza. El pago activa el usuario. Los dueños entran con su correo desde el login del landing y solo ven `my-plan/`; los superusuarios ven toda la API.

## API del panel

Todo cuelga de `/api/v1/admin/` y exige un JWT de superusuario, salvo `health/`, `auth/login/`, y `auth/me/`, `plans/` y `my-plan/`, abiertos a los dueños.

| Ruta | Uso |
| --- | --- |
| `auth/login/`, `auth/refresh/`, `auth/me/` | Sesión |
| `metrics/` | KPIs globales |
| `tenants/` | CRUD, `search`, `estado`, `page` |
| `licenses/` | CRUD, `search`, `estado`, `page` |
| `payments/` | Historial, `search`, `page` |
| `stripe/sync/` | Activa checkouts pagados sin webhook |
| `plans/` | Catálogo de planes |
| `my-plan/` | Restaurante, licencia y pagos del dueño |
| `health/` | Estado del servidor |
