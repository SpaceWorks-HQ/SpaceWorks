# Backend

Django REST API for Space Works.

## Run Locally

From the repo root, start Postgres:

```powershell
docker compose up -d db
```

Then run the backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

The backend runs at:

```text
http://localhost:8000/api/v1
```

## Admin Panel

The Django admin panel is backend-only:

```text
Local: http://localhost:8000/control/
Docker: http://localhost:8001/control/
```

Create an admin user with:

```powershell
cd backend
python manage.py createsuperuser
```

In Docker:

```powershell
docker compose exec backend python manage.py createsuperuser
```

Use the admin panel to create makerspaces. Public makerspaces need:

```text
public_inventory_enabled=True
unique slug
```

The frontend public directory lists enabled makerspaces automatically through:

```text
GET /api/v1/public/makerspaces/
```

## API Docs

Swagger UI and ReDoc are set up in the backend through `drf-spectacular`.

```text
Swagger UI: http://localhost:8000/docs/
ReDoc: http://localhost:8000/redoc/
OpenAPI schema: http://localhost:8000/schema/
```

When running through `docker compose`, the backend host port is `8001`:

```text
Backend API: http://localhost:8001/api/v1
Swagger UI: http://localhost:8001/docs/
ReDoc: http://localhost:8001/redoc/
OpenAPI schema: http://localhost:8001/schema/
```

The routes are defined in `config/urls.py`:

```text
/
/control/
/schema/
/docs/
/redoc/
```

Important workflow routes:

```text
POST /api/v1/public/<makerspace_slug>/tools/evidence-url
POST /api/v1/public/<makerspace_slug>/tools/checkout
POST /api/v1/public/<makerspace_slug>/tools/return
GET/POST /api/v1/admin/makerspace/<makerspace_id>/direct-loans
POST /api/v1/admin/makerspaces/<makerspace_id>/walk-in-members
POST /api/v1/admin/direct-loans/<id>/return
POST /api/v1/admin/qr/resolve
```

The Check-In API client is retired; requester identity now comes from a member account, from the
deployment's own OIDC provider, or from a staff-created walk-in record.

The public tool and direct-loan issue paths require issue evidence. Return paths require return
evidence plus notes/remarks before inventory availability is updated. QR resolve responses include
`allowed_actions`, but the scanner UI must still submit through the dedicated workflow endpoint.

## Run Tests

```powershell
cd backend
pytest
python manage.py spectacular --format openapi-json --file ..\frontend\openapi-schema.json
cd ..\frontend
npm run generate:api
npm run build
```
