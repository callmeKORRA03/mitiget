# Mitiget Access Governance API

A Django REST Framework backend for tenant-isolated role-based access, Risk and Internal Audit module licences, scoped permissions, audit of access changes, and optional AI-generated access review summaries.

## Architecture

- **Tenant membership** is the authority boundary. Clients send `X-Tenant-ID`; the authenticated user must have an active membership in that tenant for every tenant API.
- **Super Admin** manages members, organisation nodes, module licences, module assignments, and permission grants. Super Admins are explicitly denied access to module business endpoints.
- **Module Admin** receives full CRUD and workflow access only for each explicitly assigned module. Every request still checks the corresponding active licence.
- **Regular User** needs a module-specific grant. A grant scoped to an organisation node applies to that node and descendants; a grant without a node applies tenant-wide. List endpoints filter records to the same scope.
- **AI summaries** are advisory descriptions of access-change events only. Authorization never calls the AI provider. The local deterministic summary works without credentials; OpenAI is optional.

## Quick start with Docker

1. Copy `.env.example` to `.env`; replace `DJANGO_SECRET_KEY` and the PostgreSQL and demo passwords.
2. Run `docker compose up --build`.
3. Open Swagger at `http://localhost:8000/api/docs/`.

Compose waits for PostgreSQL, applies migrations and seeds a demo tenant. Demo credentials come from `DEMO_SUPER_ADMIN_EMAIL`, `DEMO_SUPER_ADMIN_PASSWORD`, `DEMO_USER_EMAIL`, and `DEMO_USER_PASSWORD` in `.env`. The example values are for local demonstrations only.

## Local setup

Requires Python 3.11+ and PostgreSQL 14+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Set POSTGRES_HOST, DB credentials, DJANGO_SECRET_KEY in .env
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
python manage.py runserver
```

For a quick local test run without PostgreSQL, set `USE_SQLITE=true` for that command. PostgreSQL remains the configured primary database and is used by Docker Compose.

```powershell
$env:USE_SQLITE='true'
python manage.py test governance
```

## Authentication and tenant selection

Obtain a short-lived access token with email and password:

```http
POST /api/auth/token/
Content-Type: application/json

{"email":"admin@example.test","password":"ChangeMe-123!"}
```

Response includes `access` and `refresh` JWTs. Send the access token and tenant UUID on tenant-scoped calls:

```http
Authorization: Bearer <access>
X-Tenant-ID: <tenant-uuid>
```

`GET /api/tenants/` lists the caller's active tenant memberships. JWT authentication does not itself grant tenant or module access.

## Example workflow

1. Sign in as the demo Super Admin, then call `GET /api/tenants/` and use the demo tenant ID in `X-Tenant-ID`.
2. `GET /api/admin/licenses/` shows the seeded licences. To deactivate a module, `PUT /api/admin/licenses/risk/` with `{"active":false}`. All Risk API calls then fail with 403, including calls by a module admin.
3. Create users with `POST /api/admin/users/`, for example `{"email":"analyst@example.test","password":"Strong-password-123!","role":"user"}`. User passwords are checked against Django's configured password validators.
4. Create an org node with `POST /api/org-nodes/`, such as `{"name":"West Branch","kind":"branch","parent":<root-node-id>}`.
5. Grant scoped access with `POST /api/admin/grants/`:

```json
{"target_user_id": 2, "module":"risk", "permission":"view_risk", "node": 3}
```

6. The user can now call `GET /api/risks/` and see only risks in node 3 and its descendants. `POST /api/risks/` additionally requires `create_risk` in scope.
7. Grant `approve_finding` to an Internal Audit member to allow the `POST /api/findings/{id}/approve/` workflow action.
8. `DELETE /api/admin/grants/{grant_id}/` revokes a grant. `GET /api/admin/access-review/` lists logged changes; `POST` generates summaries for pending changes.

Successful grant example:

```json
{"id": 14, "user_id": 2, "module":"risk", "permission":"view_risk", "node_id": 3}
```

## API surface

| Area | Routes | Purpose |
|---|---|---|
| Auth | `/api/auth/token/`, `/api/auth/token/refresh/` | Obtain/refresh JWT |
| Tenant | `GET /api/tenants/` | List caller memberships |
| Members | `GET/POST /api/admin/users/` | List/create tenant users |
| Org structure | `/api/org-nodes/` | Tenant-scoped node CRUD (Super Admin) |
| Licences | `GET /api/admin/licenses/`, `PUT /api/admin/licenses/{risk\|audit}/` | Read/update module licences |
| Module admins | `POST /api/admin/memberships/{id}/modules/`, `DELETE .../{module}/` | Assign/revoke a module admin module |
| Grants | `GET/POST /api/admin/grants/`, `DELETE /api/admin/grants/{id}/` | List, grant and revoke scoped permissions |
| Risk | `/api/risks/` | Licensed and authorized Risk CRUD |
| Audit | `/api/findings/`, `POST /api/findings/{id}/approve/`, `POST .../close/` | Findings and scoped workflow actions |
| Access review | `GET/POST /api/admin/access-review/` | View logged access changes and summarize |
| Docs | `/api/docs/`, `/api/schema/` | Swagger UI and OpenAPI schema |

Permissions include `view_risk`, `create_risk`, `edit_risk`, `delete_risk`, `view_audit`, `create_audit`, `edit_audit`, `approve_finding`, and `close_finding`.

## AI configuration

Set `AI_PROVIDER=openai` and `AI_API_KEY` to enable the optional OpenAI summarizer. `AI_MODEL` selects the model. If the provider is unset, lacks a key, or fails, a local summary is returned. Access decisions are always made synchronously by deterministic server-side checks.

## Security and production notes

- Use HTTPS, a strong random secret key, secret management, database backups, and production-grade PostgreSQL credentials.
- The demo seeder creates credentials intended for local assessment walkthroughs; rotate them before deployment.
- Tenant IDs are selectors, never credentials. Every request is checked against the caller's active membership.
- API business data is not registered in Django Admin. Use the API authorization layer for module data.
- Schema: `python manage.py spectacular --file schema.yml --validate`.

## Important files

- `config/settings.py` â€” database, JWT, DRF, OpenAPI, environment configuration.
- `governance/models.py` â€” tenant, memberships, licences, hierarchy, grants, business data, access audit.
- `governance/services/access.py` â€” tenant lookup, licence checks, grant and hierarchy enforcement.
- `governance/services/ai.py` â€” optional AI provider abstraction and safe local fallback.
- `governance/serializers.py` â€” API validation, tenant and permission consistency checks.
- `governance/views.py`, `governance/urls.py` â€” APIs and business workflows.
- `governance/migrations/` â€” schema history.
- `governance/tests.py` â€” authorization, tenant, licence and hierarchy tests.
- `governance/management/commands/seed_demo.py` â€” repeatable demo data bootstrap.
- `docker-compose.yml`, `Dockerfile`, `.env.example` â€” containerized setup.

## Interview walkthrough

Show a successful Super Admin login and tenant lookup; explain that the tenant header is checked against membership. Create a branch, user and scoped Risk grant. Show that the user can view descendant risks, receives 403 when creating without `create_risk`, and cannot access another tenant's node. Assign a Risk Module Admin and demonstrate module-only CRUD. Deactivate the Risk licence and show that both Super Admin and Module Admin data calls are denied. Finally show grant revocation and the access review summary endpoint.

## Potential interview questions

1. Why is the tenant ID a selector rather than a claim trusted from the client?
2. How would you prevent tenant leaks in a new endpoint or background task?
3. What are the trade-offs between adjacency-list hierarchy storage and a closure table at scale?
4. Why does a module admin still require an active module licence?
5. How would you model separation of duties for approving audit findings?
6. How should grant/revoke audit events be made tamper-evident and retained?
7. What would you change to support multiple roles per user per tenant?
8. How would you test revocation consistency with caches or long-running sessions?
9. What limits and privacy controls would you add to the optional AI summary provider?
10. How would you add rate limiting, observability and idempotency for production use?


## Browser administration console

The Django Template dashboard runs in the same application as the API; there is no separate frontend build or JavaScript package install.

- Frontend: `http://127.0.0.1:8000/app/`
- Sign in: `http://127.0.0.1:8000/app/login/`
- API docs: `http://127.0.0.1:8000/api/docs/`

Start it locally with PostgreSQL configured in `.env`, or use the existing SQLite development option:

```powershell
$env:USE_SQLITE='true'
python manage.py migrate
python manage.py seed_demo
python manage.py collectstatic --noinput
python manage.py runserver
```

Use `DEMO_SUPER_ADMIN_EMAIL` and `DEMO_SUPER_ADMIN_PASSWORD` from `.env` (the example values are `admin@example.test` and `ChangeMe-123!`). The JWT access and refresh tokens live in browser `sessionStorage` for the current tab session; sign out clears them. Tenant selection comes from `GET /api/tenants/`, and protected API requests include the selected `X-Tenant-ID` and Bearer token.

### Demonstrate the three roles

1. Sign in as the seeded Super Admin. Review tenant users and licences, create a regular user, and grant a scoped permission in **Permissions**.
2. In **Users & roles**, create a Module Admin user, then assign Risk or Internal Audit. Sign out and sign in as that account to demonstrate access to the assigned module. Requests to other modules are still checked by the API.
3. Sign out and sign in as the regular user to show scoped access. To demonstrate a 403, try a module or operation without a grant. The dashboard RBAC panel can also run API probes and an unauthenticated request to show the actual HTTP status.
4. As Super Admin, disable a module licence in **Module licences**. Then return to the Module Admin and repeat the module probe: the API should deny access while the licence is inactive. Re-enable the licence afterwards if you want to continue the demo.

The API is authoritative. The dashboard does not hide the backend's authorization decisions; it displays the response returned by the API. Licence details, member administration, and grant management are restricted by the existing backend endpoints to Super Admins. Regular and Module Admin users may see 403 responses on those administration pages.

The frontend uses Django templates in `governance/templates/governance/`, styles in `governance/static/governance/css/app.css`, browser code in `governance/static/governance/js/app.js`, and page routes in `governance/web_views.py`.
