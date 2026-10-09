"""Helpers shared by the two-factor views and the profile page."""
import base64
import io
from base64 import b32encode

import qrcode
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

BACKUP_CODE_COUNT = 10
TOTP_DEVICE_NAME = 'Authenticator app'
BACKUP_DEVICE_NAME = 'Backup codes'


def get_totp_device(user):
    """The user's confirmed authenticator, or None when 2FA is not enabled."""
    return TOTPDevice.objects.devices_for_user(user, confirmed=True).first()


def get_backup_device(user):
    return StaticDevice.objects.devices_for_user(user, confirmed=True).first()


def backup_code_count(user):
    device = get_backup_device(user)
    return device.token_set.count() if device else 0


def regenerate_backup_codes(user):
    """Replace any existing backup codes with a fresh set and return the plain codes."""
    StaticDevice.objects.devices_for_user(user, confirmed=None).delete()
    device = StaticDevice.objects.create(user=user, name=BACKUP_DEVICE_NAME, confirmed=True)
    tokens = [
        StaticToken(device=device, token=StaticToken.random_token())
        for _ in range(BACKUP_CODE_COUNT)
    ]
    StaticToken.objects.bulk_create(tokens)
    return [t.token for t in tokens]


def disable_two_factor(user):
    TOTPDevice.objects.devices_for_user(user, confirmed=None).delete()
    StaticDevice.objects.devices_for_user(user, confirmed=None).delete()


def manual_key(device):
    """Base32 secret in groups of four, for people who type it in rather than scan."""
    key = b32encode(device.bin_key).decode()
    return ' '.join(key[i:i + 4] for i in range(0, len(key), 4))


def qr_code_data_uri(text):
    image = qrcode.make(text, box_size=6, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f'data:image/png;base64,{encoded}'
