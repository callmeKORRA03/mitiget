from django.test import TestCase
from rest_framework.test import APIClient
from governance.models import User, Tenant, Membership, OrgNode, ModuleLicense, ModuleAssignment, PermissionGrant, RiskRecord, AuditFinding

class AccessControlTests(TestCase):
    def setUp(self):
        self.client=APIClient()
        self.tenant=Tenant.objects.create(name="Tenant A",slug="tenant-a")
        self.other=Tenant.objects.create(name="Tenant B",slug="tenant-b")
        self.root=OrgNode.objects.create(tenant=self.tenant,name="Root",kind="organization")
        self.branch=OrgNode.objects.create(tenant=self.tenant,parent=self.root,name="Branch",kind="branch")
        self.sibling=OrgNode.objects.create(tenant=self.tenant,parent=self.root,name="Sibling",kind="branch")
        self.other_node=OrgNode.objects.create(tenant=self.other,name="Other",kind="organization")
        self.super=User.objects.create_user(email="admin@test.com",password="Strong-pass-123")
        self.user=User.objects.create_user(email="user@test.com",password="Strong-pass-123")
        self.module_admin=User.objects.create_user(email="module@test.com",password="Strong-pass-123")
        self.super_m=Membership.objects.create(tenant=self.tenant,user=self.super,role="super_admin")
        self.user_m=Membership.objects.create(tenant=self.tenant,user=self.user,role="user")
        self.admin_m=Membership.objects.create(tenant=self.tenant,user=self.module_admin,role="module_admin")
        ModuleLicense.objects.create(tenant=self.tenant,module="risk")
        ModuleLicense.objects.create(tenant=self.tenant,module="audit")
        ModuleAssignment.objects.create(membership=self.admin_m,module="risk")
        self.risk=RiskRecord.objects.create(tenant=self.tenant,node=self.branch,title="R1",created_by=self.user)
    def auth(self,user,tenant=None): self.client.force_authenticate(user); self.client.credentials(HTTP_X_TENANT_ID=str(tenant or self.tenant.id))
    def test_unlicensed_module_denied_even_to_super_admin(self):
        ModuleLicense.objects.filter(tenant=self.tenant,module="risk").update(active=False)
        self.auth(self.super)
        self.assertEqual(self.client.get("/api/risks/").status_code,403)
    def test_super_admin_cannot_read_business_data(self):
        self.auth(self.super)
        self.assertEqual(self.client.get("/api/risks/").status_code,403)
    def test_no_grant_denies_regular_user(self):
        self.auth(self.user)
        self.assertEqual(self.client.get("/api/risks/").status_code,403)
    def test_scoped_grant_includes_descendants_and_excludes_outside_nodes(self):
        PermissionGrant.objects.create(membership=self.user_m,module="risk",permission="view_risk",node=self.root,granted_by=self.super)
        self.auth(self.user)
        self.assertEqual(self.client.get("/api/risks/").status_code,200)
        RiskRecord.objects.create(tenant=self.tenant,node=self.root,title="Root",created_by=self.user)
        self.assertEqual(len(self.client.get("/api/risks/").data),2)
    def test_module_admin_only_assigned_module(self):
        self.auth(self.module_admin)
        self.assertEqual(self.client.get("/api/risks/").status_code,200)
        self.assertEqual(self.client.get("/api/findings/").status_code,403)
    def test_module_admin_grant_cannot_cross_module_boundary(self):
        PermissionGrant.objects.create(membership=self.admin_m,module="audit",permission="view_audit",node=None,granted_by=self.super)
        self.auth(self.module_admin)
        self.assertEqual(self.client.get("/api/findings/").status_code,403)

        self.auth(self.super)
        response=self.client.post("/api/admin/grants/",{"target_user_id":self.module_admin.id,"module":"audit","permission":"view_audit"},format="json")
        self.assertEqual(response.status_code,400)
    def test_edit_audit_cannot_change_finding_status(self):
        finding=AuditFinding.objects.create(tenant=self.tenant,node=self.branch,title="Finding",created_by=self.user)
        PermissionGrant.objects.create(membership=self.user_m,module="audit",permission="edit_audit",node=self.branch,granted_by=self.super)
        self.auth(self.user)
        for status in ["approved","closed"]:
            response=self.client.patch(f"/api/findings/{finding.id}/",{"status":status},format="json")
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.data["status"],AuditFinding.Status.OPEN)
        finding.refresh_from_db()
        self.assertEqual(finding.status,AuditFinding.Status.OPEN)
    def test_tenant_membership_required(self):
        self.auth(self.user,self.other.id)
        self.assertEqual(self.client.get("/api/risks/").status_code,404)
    def test_cross_tenant_node_rejected(self):
        PermissionGrant.objects.create(membership=self.user_m,module="risk",permission="create_risk",node=None,granted_by=self.super)
        self.auth(self.user)
        response=self.client.post("/api/risks/",{"node":self.other_node.id,"title":"Escape"},format="json")
        self.assertEqual(response.status_code,400)
    def test_scoped_editor_cannot_move_record_outside_scope(self):
        PermissionGrant.objects.create(membership=self.user_m,module="risk",permission="view_risk",node=self.branch,granted_by=self.super)
        PermissionGrant.objects.create(membership=self.user_m,module="risk",permission="edit_risk",node=self.branch,granted_by=self.super)
        self.auth(self.user)
        response=self.client.patch(f"/api/risks/{self.risk.id}/",{"node":self.sibling.id},format="json")
        self.assertEqual(response.status_code,403)
    def test_super_admin_can_grant_scoped_permission(self):
        self.auth(self.super)
        response=self.client.post("/api/admin/grants/",{"target_user_id":self.user.id,"module":"risk","permission":"view_risk","node":self.branch.id},format="json")
        self.assertEqual(response.status_code,201)
        grant = PermissionGrant.objects.get(membership=self.user_m,module="risk",permission="view_risk",node=self.branch)
        self.client.delete(f"/api/admin/grants/{grant.id}/")
        self.assertFalse(PermissionGrant.objects.filter(pk=grant.id).exists())
    def test_admin_grant_cannot_assign_unlicensed_module(self):
        ModuleLicense.objects.filter(tenant=self.tenant,module="audit").update(active=False)
        self.auth(self.super)
        response=self.client.post("/api/admin/grants/",{"target_user_id":self.user.id,"module":"audit","permission":"view_audit"},format="json")
        self.assertEqual(response.status_code,403)
