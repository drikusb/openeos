from django import forms
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice


def too_many_attempts_message(seconds):
    unit = 'second' if seconds == 1 else 'seconds'
    return f'Too many failed attempts. Please wait {seconds} {unit} before trying again.'


def _throttle_message(device):
    """django-otp's own lock-out message, or None when the device accepts attempts."""
    allowed, data = device.verify_is_allowed()
    if allowed:
        return None
    lock = data['locked_until'] - device.throttling_failure_timestamp
    return too_many_attempts_message(max(1, int(lock.total_seconds())))


class TwoFactorSetupForm(forms.Form):
    token = forms.CharField(
        label='6-digit code',
        min_length=6, max_length=8,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'autocomplete': 'one-time-code',
            'inputmode': 'numeric',
            'autofocus': True,
        }),
    )

    def __init__(self, *args, device=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.device = device

    def clean_token(self):
        token = self.cleaned_data['token'].replace(' ', '')
        locked = _throttle_message(self.device)
        if locked:
            raise forms.ValidationError(locked)
        if not self.device.verify_token(token):
            raise forms.ValidationError(
                'That code did not match. Check the time on your phone and try again.'
            )
        return token


class TwoFactorVerifyForm(forms.Form):
    token = forms.CharField(
        label='Code',
        max_length=16,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'autocomplete': 'one-time-code',
            'autofocus': True,
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.device = None

    def clean_token(self):
        token = self.cleaned_data['token'].replace(' ', '').replace('-', '')
        # Authenticator codes are all digits; anything else can only be a backup code.
        if token.isdigit():
            devices = TOTPDevice.objects.devices_for_user(self.user, confirmed=True)
        else:
            token = token.lower()
            devices = StaticDevice.objects.devices_for_user(self.user, confirmed=True)
        for device in devices:
            locked = _throttle_message(device)
            if locked:
                raise forms.ValidationError(locked)
            if device.verify_token(token):
                self.device = device
                return token
        raise forms.ValidationError('That code did not match. Please try again.')


class PasswordConfirmForm(forms.Form):
    password = forms.CharField(
        label='Current password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'autocomplete': 'current-password',
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data['password']
        if not self.user.check_password(password):
            raise forms.ValidationError('That password is not correct.')
        return password
