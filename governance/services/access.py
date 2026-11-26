from django.utils import timezone
from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, NotFound
from governance.models import Membership, ModuleLicense, ModuleAssignment, PermissionGrant, OrgNode

def tenant_context(request):
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id: raise PermissionDenied("X-Tenant-ID header is required.")
    membership = Membership.objects.select_related("tenant").filter(tenant_id=tenant_id, user=request.user, active=True).first()
    if not membership: raise NotFound("Tenant membership not found.")
    request.tenant, request.membership = membership.tenant, membership
    return membership

def licensed(tenant, module):
    return ModuleLicense.objects.filter(tenant=tenant, module=module, active=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
    ).exists()

def descendants(node):
    ids, frontier = {node.pk}, [node.pk]
    while frontier:
        children = list(OrgNode.objects.filter(parent_id__in=frontier, tenant_id=node.tenant_id).values_list("pk", flat=True))
        frontier = [i for i in children if i not in ids]
        ids.update(frontier)
    return ids

def authorize_module(request, module, permission=None, node_id=None):
    membership = getattr(request, "membership", None) or tenant_context(request)
    if not licensed(membership.tenant, module): raise PermissionDenied("Module is not licensed for this tenant.")
    if membership.role == Membership.Role.SUPER_ADMIN:
        raise PermissionDenied("Super Admins cannot access module business data.")
    if membership.role == Membership.Role.MODULE_ADMIN:
        # Module Admins are limited to assigned modules; never fall through to user grants.
        if ModuleAssignment.objects.filter(membership=membership, module=module).exists():
            return None
        raise PermissionDenied("Module Admin is not assigned to this module.")
    if permission is None: raise PermissionDenied("Permission required.")
    if node_id:
        node = OrgNode.objects.filter(pk=node_id, tenant=membership.tenant).first()
        if not node: raise PermissionDenied("Organizational node is outside this tenant.")
    grants = PermissionGrant.objects.filter(membership=membership, module=module, permission=permission)
    scopes = list(grants.values_list("node_id", flat=True))
    if not scopes: raise PermissionDenied("Permission not granted.")
    if None in scopes: return None
    allowed = set()
    for scope_id in scopes:
        scope = OrgNode.objects.get(pk=scope_id, tenant=membership.tenant)
        allowed.update(descendants(scope))
    if node_id is not None and node_id not in allowed: raise PermissionDenied("Outside granted organizational scope.")
    return allowed

def assert_super_admin(request):
    m = getattr(request, "membership", None) or tenant_context(request)
    if m.role != Membership.Role.SUPER_ADMIN: raise PermissionDenied("Super Admin role required.")
    return m
