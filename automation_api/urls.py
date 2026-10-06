from django.urls import path
from . import views, stage2, cancellation
app_name='automation_api'
urlpatterns=[
    path('cancellation/claim/', cancellation.claim, name='cancellation-claim'),
    path('cancellation/<uuid:cleanup_id>/result/', cancellation.finish, name='cancellation-result'),
    path('stage2/<uuid:attempt_id>/screenshot/', stage2.screenshot, name='stage2-screenshot'),
    path('stage2/claim/', stage2.claim, name='stage2-claim'),
    path('stage2/<uuid:attempt_id>/renew/', stage2.renew, name='stage2-renew'),
    path('stage2/<uuid:attempt_id>/result/', stage2.result, name='stage2-result'),
    path('health/',views.health,name='health'),
    path('preparation/claim/',views.claim,name='claim'),
    path('preparation/current/',views.current,name='current'),
    path('preparation/<uuid:attempt_id>/recovery/',views.preparation_recovery,name='preparation-recovery'),
    path('preparation/<uuid:attempt_id>/renew/',views.renew,name='renew'),
    path('preparation/<uuid:attempt_id>/pdf/',views.pdf,name='pdf'),
    path('preparation/<uuid:attempt_id>/result/',views.result,name='result'),
]
