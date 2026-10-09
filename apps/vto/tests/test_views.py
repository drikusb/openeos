from django.test import TestCase
from django.contrib.auth.models import User

from apps.accounts.models import Membership, Organization


class VTOPrintColourAdjustTest(TestCase):
    """Regression test: browsers drop background colours when printing by default,
    which was silently stripping the colour off the Rock and Issue status badges."""

    def setUp(self):
        self.org = Organization.objects.create(name='Print Colour Org')
        self.user = User.objects.create_user(username='printcolouruser', password='pw')
        Membership.objects.create(user=self.user, organization=self.org)

    def test_print_colour_is_forced_on(self):
        self.client.force_login(self.user)
        resp = self.client.get('/vto/print/')
        self.assertContains(resp, 'print-color-adjust: exact')
