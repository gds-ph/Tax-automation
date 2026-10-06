from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@never_cache
@login_required
@require_GET
def registered_users(request):
    if not request.user.is_active or not request.user.is_superuser:
        raise PermissionDenied
    users = get_user_model().objects.select_related('feishuidentity').order_by('-date_joined', 'pk')
    query = request.GET.get('q', '').strip()[:150]
    if query:
        users = users.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) |
                             Q(username__icontains=query) | Q(email__icontains=query))
    return render(request, 'accounts/users.html', {
        'section': 'users', 'query': query,
        'page_obj': Paginator(users, 30).get_page(request.GET.get('page')),
    })


class DashboardLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        from .feishu import configured
        return {**super().get_context_data(**kwargs), 'feishu_enabled': configured()}


class DashboardLogoutView(LogoutView):
    """Django accepts logout by POST only, protected by CSRF middleware."""

    next_page = "login"
