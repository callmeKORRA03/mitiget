from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from governance.models import *
from governance.serializers import *
from governance.services.access import tenant_context, assert_super_admin, authorize_module, descendants
from governance.services.ai import summarize_access_change

class TenantView(APIView):
    serializer_class=TenantMembershipSerializer
    permission_classes=[IsAuthenticated]
    def get(self, request):
        return Response([{"id":str(m.tenant_id),"name":m.tenant.name,"role":m.role} for m in request.user.memberships.filter(active=True).select_related("tenant")])

class TenantAPIView(APIView):
    permission_classes=[IsAuthenticated]
    def initial(self, request, *args, **kwargs):
        super().initial(request,*args,**kwargs); tenant_context(request)

class NodeViewSet(viewsets.ModelViewSet):
    queryset=OrgNode.objects.none()
    serializer_class=OrgNodeSerializer
    def initial(self, request,*args,**kwargs): super().initial(request,*args,**kwargs); self.membership=tenant_context(request); assert_super_admin(request)
    def get_queryset(self): return OrgNode.objects.filter(tenant=self.membership.tenant).select_related("parent")
    def get_serializer_context(self): return {**super().get_serializer_context(),"tenant":self.membership.tenant}
    def perform_create(self,serializer): serializer.save(tenant=self.membership.tenant)

class LicenseView(TenantAPIView):
    serializer_class=ModuleLicenseSerializer
    def get(self,request):
        assert_super_admin(request)
        return Response(ModuleLicenseSerializer(ModuleLicense.objects.filter(tenant=request.tenant),many=True).data)

class UserView(TenantAPIView):
    serializer_class=CreateUserSerializer
    def get(self,request):
        assert_super_admin(request)
        memberships=Membership.objects.filter(tenant=request.tenant,active=True).select_related("user")
        return Response([{"membership_id":m.id,"user":UserSerializer(m.user).data,"role":m.role,"modules":list(m.module_assignments.values_list("module",flat=True))} for m in memberships])
    @transaction.atomic
    def post(self,request):
        m=assert_super_admin(request); serializer=CreateUserSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        if data["role"]==Membership.Role.SUPER_ADMIN: return Response({"detail":"Super Admin membership cannot be self-provisioned through this endpoint."},status=400)
        user=User.objects.filter(email=data["email"]).first()
        if user and Membership.objects.filter(user=user,tenant=m.tenant).exists(): return Response({"detail":"User is already a tenant member."},status=400)
        if not user: user=User.objects.create_user(email=data["email"],password=data["password"],first_name=data.get("first_name",""),last_name=data.get("last_name",""))
        else:
            user.first_name=data.get("first_name",user.first_name); user.last_name=data.get("last_name",user.last_name); user.save()
        membership=Membership.objects.create(tenant=m.tenant,user=user,role=data["role"])
        return Response({"membership_id":membership.id,"user":UserSerializer(user).data,"role":membership.role},status=201)

class ModuleAssignmentView(TenantAPIView):
    serializer_class=ModuleAssignmentSerializer
    def post(self,request,membership_id):
        assert_super_admin(request); target=get_object_or_404(Membership,pk=membership_id,tenant=request.tenant)
        module=request.data.get("module")
        if target.role == Membership.Role.SUPER_ADMIN: return Response({"detail":"Super Admin memberships cannot be assigned as Module Admins."},status=400)
        if module not in ModuleLicense.Module.values: return Response({"detail":"Unknown module."},status=400)
        if not ModuleLicense.objects.filter(tenant=request.tenant,module=module,active=True).filter(Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())).exists(): return Response({"detail":"Cannot assign an unlicensed module."},status=403)
        target.role=Membership.Role.MODULE_ADMIN; target.save(update_fields=["role"])
        ModuleAssignment.objects.get_or_create(membership=target,module=module)
        return Response({"membership_id":target.id,"module":module,"role":target.role},status=201)

class GrantView(TenantAPIView):
    serializer_class=PermissionGrantSerializer
    def get(self,request):
        assert_super_admin(request)
        rows=PermissionGrant.objects.filter(membership__tenant=request.tenant).select_related("membership__user","node")
        return Response([{"id":g.id,"user_id":g.membership.user_id,"email":g.membership.user.email,"module":g.module,"permission":g.permission,"node_id":g.node_id,"scope":g.node.name if g.node else "tenant-wide"} for g in rows])
    def post(self,request):
        actor=assert_super_admin(request); serializer=PermissionGrantSerializer(data=request.data,context={"membership":actor}); serializer.is_valid(raise_exception=True)
        membership=serializer.validated_data["membership"]; module=serializer.validated_data["module"]
        if not ModuleLicense.objects.filter(tenant=actor.tenant,module=module,active=True).filter(Q(expires_at__isnull=True)|Q(expires_at__gt=timezone.now())).exists(): return Response({"detail":"Cannot grant permissions in an unlicensed module."},status=403)
        grant=serializer.save(granted_by=request.user)
        AccessChange.objects.create(tenant=actor.tenant,actor=request.user,action="grant",target_email=membership.user.email,module=module,permission=grant.permission,scope_name=grant.node.name if grant.node else "tenant-wide")
        return Response({"id":grant.id,"user_id":membership.user_id,"module":module,"permission":grant.permission,"node_id":grant.node_id},status=201)

class LicenseDetailView(TenantAPIView):
    serializer_class=ModuleLicenseSerializer
    def put(self,request,module):
        assert_super_admin(request)
        if module not in ModuleLicense.Module.values: return Response({"detail":"Unknown module."},status=400)
        ser=ModuleLicenseSerializer(data={**request.data,"module":module})
        ser.is_valid(raise_exception=True)
        obj,_=ModuleLicense.objects.update_or_create(tenant=request.tenant,module=module,defaults={"active":ser.validated_data["active"],"expires_at":ser.validated_data.get("expires_at")})
        return Response(ModuleLicenseSerializer(obj).data)

class GrantDetailView(TenantAPIView):
    serializer_class=PermissionGrantSerializer
    def delete(self,request,grant_id):
        actor=assert_super_admin(request); grant=get_object_or_404(PermissionGrant,pk=grant_id,membership__tenant=actor.tenant)
        AccessChange.objects.create(tenant=actor.tenant,actor=request.user,action="revoke",target_email=grant.membership.user.email,module=grant.module,permission=grant.permission,scope_name=grant.node.name if grant.node else "tenant-wide")
        grant.delete(); return Response(status=204)

class ModuleAssignmentDeleteView(TenantAPIView):
    serializer_class=ModuleAssignmentSerializer
    def delete(self,request,membership_id,module):
        assert_super_admin(request); target=get_object_or_404(Membership,pk=membership_id,tenant=request.tenant)
        if target.role==Membership.Role.SUPER_ADMIN: return Response({"detail":"Cannot alter a Super Admin membership."},status=400)
        ModuleAssignment.objects.filter(membership=target,module=module).delete()
        if not target.module_assignments.exists() and target.role==Membership.Role.MODULE_ADMIN: target.role=Membership.Role.USER; target.save(update_fields=["role"])
        return Response(status=204)

class RiskViewSet(viewsets.ModelViewSet):
    queryset=RiskRecord.objects.none()
    serializer_class=RiskSerializer
    def initial(self,request,*args,**kwargs): super().initial(request,*args,**kwargs); self.membership=tenant_context(request)
    def get_perm(self): return {"list":"view_risk","retrieve":"view_risk","create":"create_risk","update":"edit_risk","partial_update":"edit_risk","destroy":"delete_risk"}[self.action]
    def get_queryset(self):
        scope=authorize_module(self.request,"risk",self.get_perm())
        qs=RiskRecord.objects.filter(tenant=self.membership.tenant).select_related("node")
        return qs.filter(node_id__in=scope) if scope is not None else qs
    def get_serializer_context(self): return {**super().get_serializer_context(),"tenant":self.membership.tenant}
    def perform_create(self,serializer):
        authorize_module(self.request,"risk","create_risk",serializer.validated_data["node"].id); serializer.save(tenant=self.membership.tenant,created_by=self.request.user)
    def perform_update(self,serializer):
        authorize_module(self.request,"risk","edit_risk",serializer.instance.node_id)
        new_node=serializer.validated_data.get("node",serializer.instance.node)
        authorize_module(self.request,"risk","edit_risk",new_node.id)
        serializer.save()
    def perform_destroy(self,instance): authorize_module(self.request,"risk","delete_risk",instance.node_id); instance.delete()

class FindingViewSet(viewsets.ModelViewSet):
    queryset=AuditFinding.objects.none()
    serializer_class=FindingSerializer
    def initial(self,request,*args,**kwargs): super().initial(request,*args,**kwargs); self.membership=tenant_context(request)
    def get_perm(self): return {"list":"view_audit","retrieve":"view_audit","create":"create_audit","update":"edit_audit","partial_update":"edit_audit","destroy":"edit_audit","approve":"approve_finding","close":"close_finding"}[self.action]
    def get_queryset(self):
        scope=authorize_module(self.request,"audit",self.get_perm())
        qs=AuditFinding.objects.filter(tenant=self.membership.tenant).select_related("node")
        return qs.filter(node_id__in=scope) if scope is not None else qs
    def get_serializer_context(self): return {**super().get_serializer_context(),"tenant":self.membership.tenant}
    def perform_create(self,serializer):
        authorize_module(self.request,"audit","create_audit",serializer.validated_data["node"].id); serializer.save(tenant=self.membership.tenant,created_by=self.request.user)
    def perform_update(self,serializer):
        authorize_module(self.request,"audit","edit_audit",serializer.instance.node_id)
        new_node=serializer.validated_data.get("node",serializer.instance.node)
        authorize_module(self.request,"audit","edit_audit",new_node.id)
        serializer.save()
    def perform_destroy(self,instance): authorize_module(self.request,"audit","edit_audit",instance.node_id); instance.delete()
    @action(detail=True,methods=["post"])
    def approve(self,request,pk=None):
        item=self.get_object(); authorize_module(request,"audit","approve_finding",item.node_id); item.status=AuditFinding.Status.APPROVED; item.save(update_fields=["status"]); return Response(self.get_serializer(item).data)
    @action(detail=True,methods=["post"])
    def close(self,request,pk=None):
        item=self.get_object(); authorize_module(request,"audit","close_finding",item.node_id); item.status=AuditFinding.Status.CLOSED; item.save(update_fields=["status"]); return Response(self.get_serializer(item).data)

class AccessReviewView(TenantAPIView):
    serializer_class=AccessChangeSerializer
    def get(self,request):
        assert_super_admin(request)
        return Response(AccessChangeSerializer(AccessChange.objects.filter(tenant=request.tenant).order_by("-created_at")[:100],many=True).data)
    def post(self,request):
        assert_super_admin(request)
        changes=AccessChange.objects.filter(tenant=request.tenant,ai_summary="").order_by("created_at")[:100]
        rows=list(changes)
        if not rows:return Response({"summary":"No unsummarized permission changes.","provider":"none"})
        summary,provider=summarize_access_change(rows)
        for row in rows: row.ai_summary=summary; row.save(update_fields=["ai_summary"])
        return Response({"summary":summary,"provider":provider,"changes":len(rows)})

from drf_spectacular.utils import extend_schema
