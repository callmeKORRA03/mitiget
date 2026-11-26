from django.test import TestCase
from rest_framework.test import APIClient
from governance.models import User, Tenant, Membership, ModuleLicense, ModuleAssignment, OrgNode, RiskRecord, PermissionGrant

class FrontendIntegrationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.tenant = Tenant.objects.create(name="Web Demo", slug="web-demo")
        self.root = OrgNode.objects.create(tenant=self.tenant, name="Head Office", kind="organization")
        self.admin = User.objects.create_user(email="web-admin@example.test", password="Strong-pass-123")
        self.module_user = User.objects.create_user(email="web-module@example.test", password="Strong-pass-123")
        self.regular = User.objects.create_user(email="web-user@example.test", password="Strong-pass-123")
        self.admin_membership = Membership.objects.create(tenant=self.tenant, user=self.admin, role=Membership.Role.SUPER_ADMIN)
        self.module_membership = Membership.objects.create(tenant=self.tenant, user=self.module_user, role=Membership.Role.MODULE_ADMIN)
        self.regular_membership = Membership.objects.create(tenant=self.tenant, user=self.regular, role=Membership.Role.USER)
        ModuleLicense.objects.create(tenant=self.tenant, module="risk", active=True)
        ModuleLicense.objects.create(tenant=self.tenant, module="audit", active=True)
        ModuleAssignment.objects.create(membership=self.module_membership, module="risk")
        RiskRecord.objects.create(tenant=self.tenant, node=self.root, title="Demo risk", created_by=self.regular)

    def test_all_browser_pages_render(self):
        paths = ["/app/login/", "/app/", "/app/users/", "/app/permissions/", "/app/licences/", "/app/risks/", "/app/audits/"]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
        css = self.client.get("/static/governance/css/app.css")
        js = self.client.get("/static/governance/js/app.js")
        self.assertEqual(css.status_code, 200)
        self.assertEqual(js.status_code, 200)
        css_body = b"".join(css.streaming_content)
        js_body = b"".join(js.streaming_content)
        self.assertIn(b"--navy", css_body)
        self.assertIn(b"sessionStorage", js_body)

    def test_jwt_login_and_tenant_header_protect_dashboard_api(self):
        response = self.client.post("/api/auth/token/", {"email": self.module_user.email, "password": "Strong-pass-123"}, format="json")
        self.assertEqual(response.status_code, 200)
        token = response.data["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/tenants/").status_code, 200)
        self.assertEqual(self.client.get("/api/risks/", HTTP_X_TENANT_ID=str(self.tenant.id)).status_code, 200)
        self.assertEqual(self.client.get("/api/risks/").status_code, 403)

    def test_admin_can_toggle_licence_and_module_admin_is_denied_afterward(self):
        response = self.client.post("/api/auth/token/", {"email": self.admin.email, "password": "Strong-pass-123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        update = self.client.put("/api/admin/licenses/risk/", {"active": False, "expires_at": None}, format="json", HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(update.status_code, 200)
        login = self.client.post("/api/auth/token/", {"email": self.module_user.email, "password": "Strong-pass-123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        denied = self.client.get("/api/risks/", HTTP_X_TENANT_ID=str(self.tenant.id))
        self.assertEqual(denied.status_code, 403)

    def test_dashboard_module_probes_match_all_three_roles(self):
        for user, expected in [(self.admin, 403), (self.module_user, 200), (self.regular, 403)]:
            with self.subTest(role=user.email):
                response = self.client.post("/api/auth/token/", {"email": user.email, "password": "Strong-pass-123"}, format="json")
                self.assertEqual(response.status_code, 200)
                self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
                probe = self.client.get("/api/risks/", HTTP_X_TENANT_ID=str(self.tenant.id))
                self.assertEqual(probe.status_code, expected)
        ModuleLicense.objects.filter(tenant=self.tenant, module="risk").update(active=False)
        response = self.client.post("/api/auth/token/", {"email": self.module_user.email, "password": "Strong-pass-123"}, format="json")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/risks/", HTTP_X_TENANT_ID=str(self.tenant.id)).status_code, 403)
