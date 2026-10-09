from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

from . import get_totp_device

TWO_FACTOR_PREFIX = '/accounts/2fa/'


class TwoFactorRequiredMiddleware:
    """Send users who have enrolled an authenticator to the verify page until they use it.

    Must sit after ``django_otp.middleware.OTPMiddleware`` so ``request.user.is_verified``
    is available.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._needs_second_factor(request):
            return redirect_to_login(
                request.get_full_path(), login_url=reverse('accounts:two_factor_verify')
            )
        return self.get_response(request)

    def _needs_second_factor(self, request):
        user = request.user
        if not user.is_authenticated or user.is_verified():
            return False
        if self._is_exempt(request.path):
            return False
        return get_totp_device(user) is not None

    @staticmethod
    def _is_exempt(path):
        # The 2FA prefix covers verify, setup, disable and backup codes; setup guards
        # itself against unverified re-enrolment.
        prefixes = [
            TWO_FACTOR_PREFIX,
            reverse('logout'),
            reverse('admin:login'),
            settings.STATIC_URL,
            settings.MEDIA_URL,
            '/healthz/',
        ]
        return any(path.startswith(prefix) for prefix in prefixes)
