"""Download the active organisation's data as one archive."""
import tempfile

from django import forms
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import FormView

from apps.audit.services import record

from .portability import (
    FORMAT_VERSION, ArchiveTooLarge, archive_filename, build_archive, collect,
)
from .scoping import get_active_org, is_org_admin


class ExportConfirmForm(forms.Form):
    """Ask the admin for their password again before handing over everything."""

    password = forms.CharField(
        label='Your password', strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control', 'autocomplete': 'current-password', 'autofocus': True,
        }),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError('That password is not right. Please try again.')
        return password


class OrganizationExportView(LoginRequiredMixin, FormView):
    """Explain what the archive holds, confirm the admin's password, send the zip.

    Open to superusers and admins of the active organisation. Every download
    is written to the audit log with its size and record counts.
    """

    template_name = 'accounts/org_export.html'
    form_class = ExportConfirmForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.org = get_active_org(request)
        if self.org is None:
            return redirect('accounts:org_setup')
        if not is_org_admin(request.user, self.org):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['org'] = self.org
        ctx['record_counts'] = [
            (queryset.model._meta.verbose_name_plural, queryset.count())
            for queryset in collect(self.org).values()
        ]
        ctx['max_megabytes'] = self.max_megabytes()
        return ctx

    def form_valid(self, form):
        now = timezone.now()
        archive = tempfile.TemporaryFile()
        try:
            manifest = build_archive(
                self.org, fileobj=archive, exported_by=self.request.user, via='web',
                max_bytes=settings.EXPORT_MAX_BYTES, exported_at=now,
            )
        except ArchiveTooLarge:
            archive.close()
            form.add_error(None, (
                f'This organisation\'s data is larger than the {self.max_megabytes()} MB '
                f'limit for downloads from the browser. Ask whoever runs this server to '
                f'export it with "python manage.py export_organization {self.org.slug}".'
            ))
            return self.form_invalid(form)

        size = archive.tell()
        archive.seek(0)
        record(
            'organization.exported', request=self.request, organization=self.org,
            target=self.org, details={
                'format_version': FORMAT_VERSION, 'via': 'web', 'size_bytes': size,
                'record_counts': manifest['record_counts'],
            },
        )
        return FileResponse(
            archive, as_attachment=True, filename=archive_filename(self.org, now),
            content_type='application/zip',
        )

    @staticmethod
    def max_megabytes():
        return settings.EXPORT_MAX_BYTES // (1024 * 1024)
