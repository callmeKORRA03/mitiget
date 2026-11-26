from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from governance.models import User, Tenant, Membership, OrgNode, ModuleLicense, ModuleAssignment, PermissionGrant, RiskRecord, AuditFinding, AccessChange, PERMISSION_CHOICES

class UserSerializer(serializers.ModelSerializer):
    class Meta: model = User; fields = ["id", "email", "first_name", "last_name", "is_active"]
class CreateUserSerializer(serializers.Serializer):
    email = serializers.EmailField(); password = serializers.CharField(write_only=True); first_name = serializers.CharField(required=False, allow_blank=True); last_name = serializers.CharField(required=False, allow_blank=True); role = serializers.ChoiceField(choices=Membership.Role.choices, default=Membership.Role.USER)
    def validate_password(self, value): validate_password(value); return value
class OrgNodeSerializer(serializers.ModelSerializer):
    class Meta: model = OrgNode; fields = ["id", "parent", "name", "kind"]
    def validate_parent(self, parent):
        if parent and parent.tenant_id != self.context["tenant"].id: raise serializers.ValidationError("Parent belongs to another tenant.")
        return parent
class ModuleLicenseSerializer(serializers.ModelSerializer):
    class Meta: model = ModuleLicense; fields = ["id", "module", "active", "expires_at"]
class PermissionGrantSerializer(serializers.ModelSerializer):
    target_user_id = serializers.IntegerField(write_only=True)
    class Meta: model = PermissionGrant; fields = ["id", "target_user_id", "module", "permission", "node", "created_at"]; read_only_fields = ["id", "created_at"]
    def validate(self, attrs):
        m = self.context["membership"]
        target_user_id = attrs.pop("target_user_id")
        target = Membership.objects.filter(tenant=m.tenant, user_id=target_user_id, active=True).first()
        if not target: raise serializers.ValidationError({"target_user_id":"Active tenant member not found."})
        if target.role == Membership.Role.SUPER_ADMIN: raise serializers.ValidationError("Cannot grant module permissions to a Super Admin.")
        # Module Admin access is managed by module assignments, not permission grants.
        if target.role == Membership.Role.MODULE_ADMIN: raise serializers.ValidationError("Module Admins receive access only through module assignments.")
        if attrs.get("node") and attrs["node"].tenant_id != m.tenant_id: raise serializers.ValidationError({"node":"Scope belongs to another tenant."})
        if attrs.get("module") == "risk" and attrs["permission"] not in {"view_risk","create_risk","edit_risk","delete_risk"}: raise serializers.ValidationError("Permission does not match risk module.")
        if attrs.get("module") == "audit" and attrs["permission"] not in {"view_audit","create_audit","edit_audit","approve_finding","close_finding"}: raise serializers.ValidationError("Permission does not match audit module.")
        attrs["membership"] = target
        return attrs
class RiskSerializer(serializers.ModelSerializer):
    class Meta: model = RiskRecord; fields = ["id", "node", "title", "description", "severity", "created_by", "created_at"]; read_only_fields = ["id", "created_by", "created_at"]
    def validate_node(self, node):
        if node.tenant_id != self.context["tenant"].id: raise serializers.ValidationError("Node belongs to another tenant.")
        return node
class FindingSerializer(serializers.ModelSerializer):
    # Finding status is workflow-controlled and cannot be changed by ordinary writes.
    class Meta: model = AuditFinding; fields = ["id", "node", "title", "description", "status", "created_by", "created_at"]; read_only_fields = ["id", "status", "created_by", "created_at"]
    def validate_node(self, node):
        if node.tenant_id != self.context["tenant"].id: raise serializers.ValidationError("Node belongs to another tenant.")
        return node
class AccessChangeSerializer(serializers.ModelSerializer):
    class Meta: model = AccessChange; fields = ["id", "action", "target_email", "module", "permission", "scope_name", "created_at", "ai_summary"]

class TenantMembershipSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()

class ModuleAssignmentSerializer(serializers.Serializer):
    module = serializers.ChoiceField(choices=ModuleLicense.Module.choices)
