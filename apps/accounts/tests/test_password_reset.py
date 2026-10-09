from django.test import TestCase


class PasswordResetFormTemplateTest(TestCase):
    """The reset form must render the project's template, not the admin's (#42)."""

    def test_reset_form_uses_the_project_template(self):
        resp = self.client.get('/accounts/password_reset/')
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'registration/password_reset_form.html')
        self.assertContains(resp, 'Reset your password')
        self.assertContains(resp, 'Send reset link')
        self.assertNotContains(resp, 'Django site admin')
