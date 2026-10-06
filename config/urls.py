"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path

from accounts.views import DashboardLoginView, DashboardLogoutView, registered_users
from accounts import feishu
from audit.views import logs, settings_page

urlpatterns = [
    path("settings/users/", registered_users, name="registered-users"),
    path('logs/', logs, name='app-logs'),
    path('settings/operations/', settings_page, name='operation-settings'),
    path('auth/feishu/login/', feishu.start, name='feishu-login'),
    path('auth/feishu/callback/', feishu.callback, name='feishu-callback'),
    path('login/', DashboardLoginView.as_view(), name='login'),
    path('logout/', DashboardLogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/agent/', include('automation_api.urls')),
    path('', include('workorders.urls')),
]
