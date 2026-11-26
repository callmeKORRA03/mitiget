from django.core.management.base import BaseCommand
from django.db import transaction
from governance.models import Tenant, User, Membership, OrgNode, ModuleLicense, PermissionGrant
class Command(BaseCommand):
    help="Create a demonstrable tenant and governance data. Credentials come from environment variables."
    @transaction.atomic
    def handle(self,*args,**options):
        tenant,_=Tenant.objects.get_or_create(slug="demo",defaults={"name":"Mitiget Demo Ltd"})
        root,_=OrgNode.objects.get_or_create(tenant=tenant,parent=None,name="Head Office",defaults={"kind":"organization"})
        branch,_=OrgNode.objects.get_or_create(tenant=tenant,parent=root,name="Lagos Branch",defaults={"kind":"branch"})
        for module in ["risk","audit"]: ModuleLicense.objects.update_or_create(tenant=tenant,module=module,defaults={"active":True,"expires_at":None})
        records=[("DEMO_SUPER_ADMIN_EMAIL","DEMO_SUPER_ADMIN_PASSWORD","super_admin"),("DEMO_USER_EMAIL","DEMO_USER_PASSWORD","user")]
        members={}
        for email_key,password_key,role in records:
            email=__import__("os").getenv(email_key,"".join(["demo-",role,"@example.test"]))
            password=__import__("os").getenv(password_key,"ChangeMe-123!" )
            user,_=User.objects.get_or_create(email=email,defaults={"is_active":True})
            if not user.password or not user.has_usable_password(): user.set_password(password); user.save(update_fields=["password"])
            member,_=Membership.objects.get_or_create(tenant=tenant,user=user,defaults={"role":role})
            members[role]=member
        user=members["user"]
        PermissionGrant.objects.get_or_create(membership=user,module="risk",permission="view_risk",node=branch,defaults={"granted_by":members["super_admin"].user})
        self.stdout.write(self.style.SUCCESS(f"Demo tenant ready: {tenant.id}; Super Admin and regular user credentials are in env vars or documented defaults."))
