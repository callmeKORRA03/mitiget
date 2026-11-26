from django.urls import path, include
from rest_framework.routers import DefaultRouter
from governance.views import TenantView, NodeViewSet, LicenseView, LicenseDetailView, UserView, ModuleAssignmentView, ModuleAssignmentDeleteView, GrantView, GrantDetailView, RiskViewSet, FindingViewSet, AccessReviewView
router=DefaultRouter()
router.register("org-nodes",NodeViewSet,basename="org-node")
router.register("risks",RiskViewSet,basename="risk")
router.register("findings",FindingViewSet,basename="finding")
urlpatterns=[
    path("tenants/",TenantView.as_view(),name="tenants"),
    path("admin/users/",UserView.as_view(),name="users"),
    path("admin/licenses/",LicenseView.as_view(),name="licenses"),
    path("admin/licenses/<str:module>/",LicenseDetailView.as_view(),name="license-detail"),
    path("admin/memberships/<int:membership_id>/modules/",ModuleAssignmentView.as_view(),name="module-assignment"),
    path("admin/memberships/<int:membership_id>/modules/<str:module>/",ModuleAssignmentDeleteView.as_view(),name="module-assignment-delete"),
    path("admin/grants/",GrantView.as_view(),name="grants"),
    path("admin/grants/<int:grant_id>/",GrantDetailView.as_view(),name="grant-detail"),
    path("admin/access-review/",AccessReviewView.as_view(),name="access-review"),
    path("",include(router.urls)),
]
