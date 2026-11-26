from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

PAGE_TEMPLATES = {
    "dashboard": "governance/dashboard.html",
    "users": "governance/users.html",
    "permissions": "governance/permissions.html",
    "licences": "governance/licences.html",
    "risks": "governance/risks.html",
    "audits": "governance/audits.html",
}

@require_GET
def login_page(request):
    return render(request, "governance/login.html", {"page": "login"})

@require_GET
def app_page(request, page="dashboard"):
    template = PAGE_TEMPLATES.get(page)
    if template is None:
        return redirect("app_dashboard")
    return render(request, template, {"page": page})
