import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q

from django.contrib.auth.base_user import BaseUserManager
class UserManager(BaseUserManager):
    use_in_migrations = True
    def create_user(self, email, password=None, **extra_fields):
        if not email: raise ValueError("Email is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True: raise ValueError("Superuser must have staff and superuser enabled.")
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

class Tenant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class Membership(models.Model):
    class Role(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        MODULE_ADMIN = "module_admin", "Module Admin"
        USER = "user", "Regular User"
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.USER)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user"], name="unique_tenant_membership")]

class OrgNode(models.Model):
    class Kind(models.TextChoices):
        ORGANIZATION = "organization", "Organization"
        SUBSIDIARY = "subsidiary", "Subsidiary"
        BRANCH = "branch", "Branch"
        DEPARTMENT = "department", "Department"
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="org_nodes")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "parent", "name"], name="unique_org_sibling_name")]
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent.tenant_id != self.tenant_id:
            raise ValidationError("Parent must belong to the same tenant.")

class ModuleLicense(models.Model):
    class Module(models.TextChoices):
        RISK = "risk", "Risk"
        AUDIT = "audit", "Internal Audit"
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="licenses")
    module = models.CharField(max_length=20, choices=Module.choices)
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "module"], name="unique_tenant_module_license")]

class ModuleAssignment(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="module_assignments")
    module = models.CharField(max_length=20, choices=ModuleLicense.Module.choices)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "module"], name="unique_module_assignment")]

PERMISSION_CHOICES = [
    ("view_risk", "View risks"), ("create_risk", "Create risks"), ("edit_risk", "Edit risks"),
    ("delete_risk", "Delete risks"), ("view_audit", "View audit findings"),
    ("create_audit", "Create audit findings"), ("edit_audit", "Edit audit findings"),
    ("approve_finding", "Approve findings"), ("close_finding", "Close findings"),
]
class PermissionGrant(models.Model):
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="grants")
    module = models.CharField(max_length=20, choices=ModuleLicense.Module.choices)
    permission = models.CharField(max_length=30, choices=PERMISSION_CHOICES)
    node = models.ForeignKey(OrgNode, null=True, blank=True, on_delete=models.CASCADE, related_name="grants")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="grants_made")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["membership", "module", "permission", "node"], name="unique_permission_grant_scope")]
        indexes = [models.Index(fields=["module", "permission"])]
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.node_id and self.node.tenant_id != self.membership.tenant_id:
            raise ValidationError("Scope node must belong to the member's tenant.")
        expected = "risk" if self.permission.endswith("risk") else ("audit" if self.permission.endswith("audit") or self.permission in ("approve_finding", "close_finding") else None)
        if expected and expected != self.module:
            raise ValidationError("Permission does not belong to the selected module.")

class RiskRecord(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="risks")
    node = models.ForeignKey(OrgNode, on_delete=models.PROTECT, related_name="risks")
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, default="medium")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.node.tenant_id != self.tenant_id: raise ValidationError("Node must belong to tenant.")

class AuditFinding(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        CLOSED = "closed", "Closed"
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="findings")
    node = models.ForeignKey(OrgNode, on_delete=models.PROTECT, related_name="findings")
    title = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.node.tenant_id != self.tenant_id: raise ValidationError("Node must belong to tenant.")

class AccessChange(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="access_changes")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    target_email = models.EmailField()
    module = models.CharField(max_length=20, blank=True)
    permission = models.CharField(max_length=30, blank=True)
    scope_name = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ai_summary = models.TextField(blank=True)

