from django.urls import path

from . import views, client_views, demo_reset, directory_views, cor_views

app_name = "workorders"
urlpatterns = [
    path('work-orders/<uuid:pk>/approve-stage2/', views.approve_stage2, name='approve-stage2'),
    path("", client_views.client_list, name="home"),
    path("clients/", client_views.client_list, name="clients"),
    path("clients/directory/", directory_views.detail, name="directory-client"),
    path("clients/registration-file/", directory_views.document, name="registration-file"),
    path("clients/read-cor/", cor_views.read, name="cor-read"),
    path("clients/cor-review/<uuid:draft_id>/", cor_views.review, name="cor-review"),
    path("clients/<uuid:pk>/", client_views.client_detail, name="client-detail"),
    path("clients/<uuid:pk>/reset-demo/", demo_reset.reset_demo, name="reset-demo"),
    path("clients/<uuid:pk>/filings/<uuid:profile_pk>/prepare/", client_views.prepare, name="client-prepare"),
    path("filings/", client_views.client_list, name="filing-types"),
    path("filings/<slug:filing_slug>/", views.work_order_list, name="filing-orders"),
    path("filings/<slug:filing_slug>/new/", views.work_order_create, name="filing-create"),
    path("work-orders/", views.work_order_list, name="list"),
    path("work-orders/new/", views.work_order_create, name="create"),
    path("work-orders/<uuid:pk>/", views.work_order_detail, name="detail"),
    path("work-orders/<uuid:pk>/prepared-pdf/", views.prepared_pdf_download, name="prepared-pdf"),
    path("work-orders/<uuid:pk>/edit/", views.work_order_edit, name="edit"),
    path("work-orders/<uuid:pk>/ready/", views.work_order_ready, name="ready"),
    path("work-orders/<uuid:pk>/draft/", views.work_order_draft, name="draft"),
]
