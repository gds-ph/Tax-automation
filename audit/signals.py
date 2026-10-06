from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from .operational import record

@receiver(user_logged_in)
def logged_in(sender, request, user, **kwargs):
    record('login', actor=user)

@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    record('logout', actor=user)

@receiver(user_login_failed)
def failed(sender, credentials, request, **kwargs):
    record('login_failed', level='WARNING')
