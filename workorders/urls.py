from django.urls import path

from . import views, client_views, demo_reset, directory_views, cor_views

app_name = "workorders"
from . import task_notices, sample_form

urlpatterns = [
    path('worker/cancellation-update/', views.cancellation_worker_update, name='cancellation-worker-update'),
    path('work-orders/<uuid:pk>/cancel/', views.work_order_cancel, name='cancel'),
    path('work-orders/<uuid:pk>/retry-submission/', views.retry_submission, name='retry-submission'),
    path("work-orders/<uuid:pk>/archive/", views.work_order_archive, name="archive"),
    path("sample-form/", sample_form.sample, name="sample-form"),
    path("my-tasks/notices/", task_notices.feed, name="task-notices"),
    path("my-tasks/notices/read-all/", task_notices.read_all, name="read-all-notices"),
    path("my-tasks/notices/<uuid:pk>/open/", task_notices.open_notice, name="open-notice"),
    path("my-tasks/", views.work_order_list, {"mine": True}, name="my-tasks"),
    path("work-orders/<uuid:pk>/assign/", views.assign_work_order, name="assign"),
    path('settings/gmail/', views.gmail_status, name='gmail-status'),
    path('<uuid:pk>/submission-screenshot/', views.submission_screenshot, name='submission-screenshot'),
    path('work-orders/<uuid:pk>/final-package/', views.final_package_download, name='final-package'),
    path('work-orders/<uuid:pk>/approve-stage2/', views.approve_stage2, name='approve-stage2'),
    path("overview/", views.overview, name="overview"),
    path("", client_views.client_list, name="home"),
    path("clients/", client_views.client_list, name="clients"),
    path("clients/saved/", client_views.saved_toggle, name="saved-toggle"),
    path("clients/directory/", directory_views.detail, name="directory-client"),
    path("clients/registration-file/", directory_views.document, name="registration-file"),
    path("clients/read-cor/", cor_views.read, name="cor-read"),
    path("clients/cor-review/<uuid:draft_id>/", cor_views.review, name="cor-review"),
    path("clients/<uuid:pk>/", client_views.client_detail, name="client-detail"),
    path("clients/<uuid:pk>/edit/", client_views.client_edit, name="client-edit"),
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
    path("work-orders/<uuid:pk>/retry/", views.work_order_retry, name="retry"),
    path("work-orders/<uuid:pk>/draft/", views.work_order_draft, name="draft"),
    path("work-orders/<uuid:pk>/release-interrupted/", views.release_interrupted_run, name="release-interrupted"),
    path('worker/recovery-update/', views.worker_recovery_update, name='worker-recovery-update'),
]
