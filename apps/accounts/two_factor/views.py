import django_otp
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView, View
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import (
    TOTP_DEVICE_NAME, backup_code_count, disable_two_factor, get_totp_device, manual_key,
    qr_code_data_uri, regenerate_backup_codes,
)
from .forms import (
    PasswordConfirmForm, TwoFactorSetupForm, TwoFactorVerifyForm, too_many_attempts_message,
)

VERIFY_FAILURE_LIMIT = 5
VERIFY_WAIT_SECONDS = 30
SESSION_2FA_FAILURES = 'two_factor_failures'
SESSION_2FA_LAST_FAILURE = 'two_factor_last_failure'


class VerifiedRequiredMixin(LoginRequiredMixin):
    """Require the second factor for this session before touching 2FA settings."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_verified():
            if get_totp_device(request.user):
                return redirect_to_login(
                    request.get_full_path(), login_url=reverse('accounts:two_factor_verify')
                )
            messages.info(request, 'Two-factor authentication is not enabled yet.')
            return redirect('accounts:profile')
        return super().dispatch(request, *args, **kwargs)


class TwoFactorSetupView(LoginRequiredMixin, FormView):
    form_class = TwoFactorSetupForm
    template_name = 'accounts/two_factor/setup.html'

    def dispatch(self, request, *args, **kwargs):
        # An enrolled user must prove the existing factor before replacing it.
        if request.user.is_authenticated and not request.user.is_verified():
            if get_totp_device(request.user):
                return redirect_to_login(
                    request.get_full_path(), login_url=reverse('accounts:two_factor_verify')
                )
        return super().dispatch(request, *args, **kwargs)

    def get_device(self):
        if not hasattr(self, '_device'):
            self._device = TOTPDevice.objects.devices_for_user(
                self.request.user, confirmed=False
            ).first() or TOTPDevice.objects.create(
                user=self.request.user, name=TOTP_DEVICE_NAME, confirmed=False
            )
        return self._device

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['device'] = self.get_device()
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = self.get_device()
        ctx['qr_code'] = qr_code_data_uri(device.config_url)
        ctx['manual_key'] = manual_key(device)
        ctx['already_enabled'] = get_totp_device(self.request.user) is not None
        return ctx

    def form_valid(self, form):
        device = self.get_device()
        TOTPDevice.objects.devices_for_user(self.request.user, confirmed=True).delete()
        device.confirmed = True
        device.save(update_fields=['confirmed'])
        codes = regenerate_backup_codes(self.request.user)
        django_otp.login(self.request, device)
        messages.success(self.request, 'Two-factor authentication is now enabled.')
        return render(self.request, 'accounts/two_factor/backup_codes.html', {
            'backup_codes': codes,
            'just_enabled': True,
        })


class TwoFactorVerifyView(LoginRequiredMixin, FormView):
    form_class = TwoFactorVerifyForm
    template_name = 'accounts/two_factor/verify.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.is_verified():
                return redirect(self.get_success_url())
            if not get_totp_device(request.user):
                return redirect('accounts:two_factor_setup')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['next'] = self.request.POST.get('next') or self.request.GET.get('next', '')
        return ctx

    def post(self, request, *args, **kwargs):
        wait = self._seconds_to_wait()
        if wait:
            form = self.get_form()
            form.add_error(None, too_many_attempts_message(wait))
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def _seconds_to_wait(self):
        """Light brute-force protection on top of django-otp's per-device throttle."""
        session = self.request.session
        if session.get(SESSION_2FA_FAILURES, 0) < VERIFY_FAILURE_LIMIT:
            return 0
        elapsed = timezone.now().timestamp() - session.get(SESSION_2FA_LAST_FAILURE, 0)
        remaining = VERIFY_WAIT_SECONDS - elapsed
        if remaining <= 0:
            session.pop(SESSION_2FA_FAILURES, None)
            session.pop(SESSION_2FA_LAST_FAILURE, None)
            return 0
        return int(remaining) + 1

    def form_invalid(self, form):
        session = self.request.session
        session[SESSION_2FA_FAILURES] = session.get(SESSION_2FA_FAILURES, 0) + 1
        session[SESSION_2FA_LAST_FAILURE] = timezone.now().timestamp()
        return super().form_invalid(form)

    def form_valid(self, form):
        self.request.session.pop(SESSION_2FA_FAILURES, None)
        self.request.session.pop(SESSION_2FA_LAST_FAILURE, None)
        django_otp.login(self.request, form.device)
        return redirect(self.get_success_url())

    def get_success_url(self):
        next_url = self.request.POST.get('next') or self.request.GET.get('next') or ''
        if url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return settings.LOGIN_REDIRECT_URL


class TwoFactorDisableView(VerifiedRequiredMixin, View):
    """POST-only: remove the authenticator and backup codes after a password check."""

    def post(self, request):
        form = PasswordConfirmForm(request.POST, user=request.user)
        if not form.is_valid():
            messages.error(
                request,
                'Two-factor authentication was not disabled: ' + form.errors['password'][0],
            )
            return redirect('accounts:profile')
        disable_two_factor(request.user)
        request.session.pop(django_otp.DEVICE_ID_SESSION_KEY, None)
        messages.success(request, 'Two-factor authentication is disabled.')
        return redirect('accounts:profile')


class TwoFactorBackupCodesView(VerifiedRequiredMixin, FormView):
    """Replace the backup codes with a fresh set, shown once."""

    form_class = PasswordConfirmForm
    template_name = 'accounts/two_factor/backup_codes_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['backup_code_count'] = backup_code_count(self.request.user)
        return ctx

    def form_valid(self, form):
        codes = regenerate_backup_codes(self.request.user)
        messages.success(self.request, 'New backup codes generated. The old ones no longer work.')
        return render(self.request, 'accounts/two_factor/backup_codes.html', {
            'backup_codes': codes,
            'just_enabled': False,
        })
