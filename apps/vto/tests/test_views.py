from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Organization


class VTOPrintColourAdjustTest(TestCase):
    """Regression test: browsers drop background colours when printing by default,
    which was silently stripping the colour off the Rock and Issue status badges."""

    def setUp(self):
        self.org = Organization.objects.create(name='Print Colour Org')
        self.user = User.objects.create_user(username='printcolouruser', password='pw')
        self.user.profile.organization = self.org
        self.user.profile.save()

    def test_print_colour_is_forced_on(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/print/')
        self.assertContains(resp, 'print-color-adjust: exact')
