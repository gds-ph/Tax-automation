from django.contrib import admin

from .models import BotMessage, Feedback


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('reference', 'category', 'summary', 'reporter_name', 'status', 'created_at')
    list_filter = ('status', 'category')
    search_fields = ('summary', 'details', 'reporter_name')
    list_editable = ('status',)
    readonly_fields = ('category', 'summary', 'details', 'reporter_open_id', 'reporter_name', 'reporter',
                       'chat_id', 'source_message_id', 'created_at')


@admin.register(BotMessage)
class BotMessageAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'role', 'sender_name', 'chat_type', 'short_text')
    list_filter = ('role', 'chat_type')
    search_fields = ('text', 'sender_name')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Text')
    def short_text(self, obj):
        return obj.text[:80]
