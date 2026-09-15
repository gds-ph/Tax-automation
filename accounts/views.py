from django.contrib.auth.views import LoginView, LogoutView


class DashboardLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class DashboardLogoutView(LogoutView):
    """Django accepts logout by POST only, protected by CSRF middleware."""

    next_page = "login"
