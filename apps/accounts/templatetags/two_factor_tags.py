from django import template

from apps.accounts.two_factor import backup_code_count, get_totp_device
from apps.accounts.two_factor.forms import PasswordConfirmForm

register = template.Library()


@register.simple_tag
def two_factor_status(user):
    """Data for the profile card, kept out of ProfileView so the feature stays self-contained."""
    return {
        'device': get_totp_device(user),
        'backup_code_count': backup_code_count(user),
        'password_form': PasswordConfirmForm(user=user),
    }
