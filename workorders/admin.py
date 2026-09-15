from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from .models import Client, FormDefinition, ClientFilingProfile, WorkOrder, WorkOrderSnapshot
from . import services, catalog_services


class VersionedConfigForm(forms.ModelForm):
    expected_version = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance._state.adding:
            self.fields["expected_version"].required = True
            self.initial["expected_version"] = self.instance.version

    def clean(self):
        result = super().clean()
        if not self.instance._state.adding and result.get("expected_version") != self.instance.version:
            raise ValidationError("This configuration changed. Reload before saving.")
        return result


class ConfigAdmin(admin.ModelAdmin):
    form = VersionedConfigForm
    readonly_fields = ("version", "created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        fields, _ = catalog_services.CONFIG[type(obj)]
        data = {field: getattr(obj, field) for field in fields}
        if change:
            saved = catalog_services.update_record(model=type(obj), pk=obj.pk, actor=request.user,
                expected_version=form.cleaned_data["expected_version"], changes=data)
        else:
            saved = catalog_services.create_record(model=type(obj), actor=request.user, data=data)
        obj.__dict__.update(saved.__dict__)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            from django.utils.html import escape
            return HttpResponse("Could not save. Reload and review: " + escape("; ".join(error.messages)), status=409)


@admin.register(Client)
class ClientAdmin(ConfigAdmin):
    list_display = ("client_code", "registered_name", "client_type", "rdo_code", "is_active", "version")
    list_filter = ("client_type", "is_active")
    search_fields = ("client_code", "registered_name", "trade_name")


@admin.register(FormDefinition)
class FormDefinitionAdmin(ConfigAdmin):
    list_display = ("form_code", "form_version", "display_name", "preparation_automation_available", "is_active")
    readonly_fields = ConfigAdmin.readonly_fields + ("submission_automation_available",)

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + (("definition_key", "form_code", "form_version") if obj else ())


@admin.register(ClientFilingProfile)
class ClientFilingProfileAdmin(ConfigAdmin):
    list_display = ("client", "form_definition", "is_active", "calendar_or_fiscal", "default_atc_code", "version")
    list_filter = ("is_active", "form_definition")
    search_fields = ("client__client_code", "client__registered_name")

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return fields + (("client", "form_definition") if obj else ())


@admin.register(WorkOrder)
class WorkOrderAdmin(admin.ModelAdmin):
    list_display = ("work_order_id", "client_name", "form_code", "filing_year", "filing_quarter", "status", "version")
    list_filter = ("status", "form_code", "filing_year")
    search_fields = ("work_order_id", "legacy_client_reference", "client_name")
    fields = ("work_order_id", "client", "client_filing_profile", "current_snapshot", "client_name", "legacy_client_reference",
              "combined_tin", "rdo_code", "registered_name", "registered_address", "form_code", "expected_form_number",
              "filing_year", "filing_month", "filing_quarter", "zero_filing", "zero_filing_approved", "form_data",
              "expected_return_period", "expected_saved_return_name", "status", "version", "created_by", "created_at", "updated_at")
    readonly_fields = fields
    actions = ("mark_ready", "return_to_draft", "refresh_snapshot")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if request.method == "POST":
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Use the dashboard or audited services to edit work orders.")
        return super().changeform_view(request, object_id, form_url, extra_context)

    def _run(self, request, queryset, target=None):
        for order in queryset:
            try:
                args = dict(work_order_id=order.pk, actor=request.user, expected_version=order.version)
                if target:
                    services.transition_work_order(**args, target=target)
                else:
                    services.refresh_work_order_snapshot(**args)
            except ValidationError as error:
                self.message_user(request, f"{order}: {'; '.join(error.messages)}", messages.ERROR)
            else:
                self.message_user(request, f"{order}: saved", messages.SUCCESS)

    @admin.action(description="Mark ready to prepare", permissions=["change"])
    def mark_ready(self, request, queryset):
        self._run(request, queryset, WorkOrder.Status.READY_TO_PREPARE)

    @admin.action(description="Return to draft", permissions=["change"])
    def return_to_draft(self, request, queryset):
        self._run(request, queryset, WorkOrder.Status.DRAFT)

    @admin.action(description="Refresh source snapshot and clear zero-filing confirmation", permissions=["change"])
    def refresh_snapshot(self, request, queryset):
        self._run(request, queryset)


@admin.register(WorkOrderSnapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ("work_order", "revision", "created_by", "created_at")
    readonly_fields = ("work_order", "revision", "data", "source_versions", "sha256", "created_by", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
