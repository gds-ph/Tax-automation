from django.conf import settings
from django.db import models
from django.utils import timezone


class BotMessage(models.Model):
    """One chat turn. The unique message ID also deduplicates Feishu redeliveries."""
    class Role(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'

    message_id = models.CharField(max_length=100, unique=True)
    thread_key = models.CharField(max_length=100, db_index=True)
    chat_id = models.CharField(max_length=100)
    chat_type = models.CharField(max_length=20)
    role = models.CharField(max_length=10, choices=Role.choices)
    sender_open_id = models.CharField(max_length=150, blank=True, db_index=True)
    sender_name = models.CharField(max_length=150, blank=True)
    text = models.TextField(max_length=20000)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['created_at', 'pk']


class Feedback(models.Model):
    class Category(models.TextChoices):
        BUG = 'bug', 'Bug'
        FEATURE = 'feature', 'Feature request'
        CHANGE = 'change', 'Change to existing behaviour'
        DATA = 'data', 'Data issue'
        QUESTION = 'question', 'Unanswered question'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        NEW = 'new', 'New'
        ACCEPTED = 'accepted', 'Accepted'
        DONE = 'done', 'Done'
        DECLINED = 'declined', 'Declined'

    category = models.CharField(max_length=20, choices=Category.choices)
    summary = models.CharField(max_length=200)
    details = models.TextField(max_length=8000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)
    reporter_open_id = models.CharField(max_length=150, blank=True)
    reporter_name = models.CharField(max_length=150, blank=True)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='bot_feedback')
    chat_id = models.CharField(max_length=100, blank=True)
    source_message_id = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def reference(self):
        return f'FB-{self.pk:04d}'

    def __str__(self):
        return f'{self.reference} {self.summary}'


class ApprovalAlert(models.Model):
    """A live work order already announced as awaiting submission approval, so it is announced only once."""
    work_order = models.CharField(max_length=36, unique=True)  # the live dashboard's work-order id
    client = models.CharField(max_length=255, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    chat_id = models.CharField(max_length=100, blank=True)
    message_id = models.CharField(max_length=100, blank=True)  # the alert post, so it can be removed
    announced_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f'{self.client} ({self.work_order})'


class WorkerStatus(models.Model):
    """Last seen state of a live automation worker, so going offline or back online is reported once."""
    name = models.CharField(max_length=150, unique=True)
    online = models.BooleanField(default=True)
    connection = models.CharField(max_length=100, blank=True)
    changed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f'{self.name}: {"online" if self.online else "offline"}'


class PackageAlert(models.Model):
    """A live work order whose final filing package was already seen, so it is announced at most once.
    Packages that existed when the alert was switched on are recorded with announced=False."""
    work_order = models.CharField(max_length=36, unique=True)
    client = models.CharField(max_length=255, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    announced = models.BooleanField(default=True)
    chat_id = models.CharField(max_length=100, blank=True)
    message_id = models.CharField(max_length=100, blank=True)
    seen_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f'{self.client} ({self.work_order})'
