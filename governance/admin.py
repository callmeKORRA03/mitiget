from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from governance.models import User, Tenant, Membership, OrgNode, ModuleLicense, ModuleAssignment, PermissionGrant, AccessChange
@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering=("email",); list_display=("email","is_staff","is_active"); fieldsets=((None,{"fields":("email","password")}),("Personal info",{"fields":("first_name","last_name")}), ("Permissions",{"fields":("is_active","is_staff","is_superuser","groups","user_permissions")}),("Important dates",{"fields":("last_login","date_joined")})); add_fieldsets=((None,{"classes":("wide",),"fields":("email","password1","password2")}));
for model in [Tenant,Membership,OrgNode,ModuleLicense,ModuleAssignment,PermissionGrant,AccessChange]: admin.site.register(model)
