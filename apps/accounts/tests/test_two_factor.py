import re

from django.contrib.auth.models import User
from django.test import TestCase
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.two_factor import regenerate_backup_codes

SETUP_URL = '/accounts/2fa/setup/'
VERIFY_URL = '/accounts/2fa/verify/'
DISABLE_URL = '/accounts/2fa/disable/'
BACKUP_URL = '/accounts/2fa/backup-codes/'
PASSWORD = 'correct-horse-battery'


def totp_code(device):
    code = totp(
        device.bin_key, step=device.step, t0=device.t0, digits=device.digits, drift=device.drift
    )
    return f'{code:0{device.digits}d}'


def confirmed_totp_device(user):
    return TOTPDevice.objects.create(user=user, name='Authenticator app', confirmed=True)


def shown_backup_codes(response):
    html = response.content.decode()
    block = re.search(r'<pre[^>]*id="backup-codes"[^>]*>(.*?)</pre>', html, re.S)
    return block.group(1).split()


def stored_backup_codes(user):
    return set(StaticToken.objects.filter(device__user=user).values_list('token', flat=True))


class TwoFactorTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='totp', password=PASSWORD)

    def login(self):
        self.client.login(username='totp', password=PASSWORD)

    def mark_verified(self, device):
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()

    def assertRedirectsToVerify(self, response, next_path):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f'{VERIFY_URL}?next={next_path}')


class TwoFactorSetupTest(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_setup_page_shows_qr_code_and_manual_key(self):
        resp = self.client.get(SETUP_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data:image/png;base64,')
        device = TOTPDevice.objects.get(user=self.user)
        self.assertFalse(device.confirmed)
        html = resp.content.decode()
        key_in_groups = re.search(r'<code[^>]*>([A-Z2-7 ]+)</code>', html).group(1)
        self.assertEqual(len(key_in_groups.replace(' ', '')), 32)

    def test_setup_reuses_the_unconfirmed_device(self):
        self.client.get(SETUP_URL)
        self.client.get(SETUP_URL)
        self.assertEqual(TOTPDevice.objects.filter(user=self.user).count(), 1)

    def test_wrong_code_leaves_device_unconfirmed(self):
        self.client.get(SETUP_URL)
        resp = self.client.post(SETUP_URL, {'token': '000000'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'did not match')
        self.assertFalse(TOTPDevice.objects.get(user=self.user).confirmed)
        self.assertFalse(StaticDevice.objects.filter(user=self.user).exists())

    def test_right_code_confirms_device_and_shows_backup_codes_once(self):
        self.client.get(SETUP_URL)
        device = TOTPDevice.objects.get(user=self.user)
        resp = self.client.post(SETUP_URL, {'token': totp_code(device)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Store these backup codes')
        codes = shown_backup_codes(resp)
        self.assertEqual(len(codes), 10)

        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(stored_backup_codes(self.user), set(codes))
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], device.persistent_id)

        profile = self.client.get('/profile/')
        self.assertContains(profile, 'Enabled')
        self.assertContains(profile, '10 backup codes remaining')
        for code in codes:
            self.assertNotContains(profile, code)

    def test_enrolled_but_unverified_user_cannot_re_enrol(self):
        confirmed_totp_device(self.user)
        resp = self.client.get(SETUP_URL)
        self.assertRedirectsToVerify(resp, SETUP_URL)

    def test_re_enrolment_replaces_old_device_and_backup_codes(self):
        old_device = confirmed_totp_device(self.user)
        old_codes = regenerate_backup_codes(self.user)
        self.mark_verified(old_device)

        self.client.get(SETUP_URL)
        new_device = TOTPDevice.objects.get(user=self.user, confirmed=False)
        resp = self.client.post(SETUP_URL, {'token': totp_code(new_device)})
        self.assertEqual(resp.status_code, 200)

        self.assertFalse(TOTPDevice.objects.filter(pk=old_device.pk).exists())
        self.assertTrue(TOTPDevice.objects.get(pk=new_device.pk).confirmed)
        self.assertFalse(StaticToken.objects.filter(token__in=old_codes).exists())
        self.assertEqual(StaticToken.objects.filter(device__user=self.user).count(), 10)


class TwoFactorMiddlewareTest(TwoFactorTestCase):
    def test_user_without_device_is_never_redirected(self):
        self.login()
        self.assertEqual(self.client.get('/rocks/').status_code, 200)
        self.assertEqual(self.client.get('/profile/').status_code, 200)

    def test_enrolled_user_is_redirected_to_verify_with_next(self):
        confirmed_totp_device(self.user)
        self.login()
        self.assertRedirectsToVerify(self.client.get('/'), '/')
        self.assertRedirectsToVerify(self.client.get('/rocks/'), '/rocks/')

    def test_unconfirmed_device_does_not_trigger_the_redirect(self):
        TOTPDevice.objects.create(user=self.user, name='abandoned', confirmed=False)
        self.login()
        self.assertEqual(self.client.get('/rocks/').status_code, 200)

    def test_enrolled_user_can_still_log_out(self):
        confirmed_totp_device(self.user)
        self.login()
        resp = self.client.post('/accounts/logout/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/accounts/login/')

    def test_admin_login_and_2fa_pages_are_reachable(self):
        confirmed_totp_device(self.user)
        self.login()
        self.assertEqual(self.client.get('/admin/login/').status_code, 200)
        self.assertEqual(self.client.get(VERIFY_URL).status_code, 200)

    def test_anonymous_user_is_left_to_login_required(self):
        resp = self.client.get('/rocks/')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/accounts/login/'))

    def test_verified_session_is_not_redirected(self):
        device = confirmed_totp_device(self.user)
        self.login()
        self.mark_verified(device)
        self.assertEqual(self.client.get('/rocks/').status_code, 200)


class TwoFactorVerifyTest(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.device = confirmed_totp_device(self.user)
        self.backup_codes = regenerate_backup_codes(self.user)
        self.login()

    def test_valid_totp_code_grants_access_and_honours_next(self):
        resp = self.client.post(VERIFY_URL, {'token': totp_code(self.device), 'next': '/rocks/'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/rocks/')
        self.assertEqual(self.client.session[DEVICE_ID_SESSION_KEY], self.device.persistent_id)
        self.assertEqual(self.client.get('/rocks/').status_code, 200)

    def test_off_site_next_is_ignored(self):
        resp = self.client.post(
            VERIFY_URL, {'token': totp_code(self.device), 'next': 'https://evil.example.com/'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/')

    def test_verify_page_carries_next_from_the_query_string(self):
        resp = self.client.get(f'{VERIFY_URL}?next=/rocks/')
        self.assertContains(resp, 'name="next" value="/rocks/"')

    def test_wrong_code_is_rejected(self):
        resp = self.client.post(VERIFY_URL, {'token': '000000'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'did not match')
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_backup_code_works_once_only(self):
        code = self.backup_codes[0]
        resp = self.client.post(VERIFY_URL, {'token': code.upper(), 'next': '/rocks/'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/rocks/')
        self.assertEqual(StaticToken.objects.filter(device__user=self.user).count(), 9)

        session = self.client.session
        del session[DEVICE_ID_SESSION_KEY]
        session.save()
        resp = self.client.post(VERIFY_URL, {'token': code})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'did not match')
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_five_failures_add_a_wait_even_for_a_correct_code(self):
        for _ in range(5):
            resp = self.client.post(VERIFY_URL, {'token': 'wrongcode'})
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.session['two_factor_failures'], 5)

        resp = self.client.post(VERIFY_URL, {'token': totp_code(self.device)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Too many failed attempts')
        self.assertContains(resp, 'wait 30 seconds')
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

    def test_rapid_retries_show_the_device_throttle_message(self):
        self.client.post(VERIFY_URL, {'token': '000000'})
        resp = self.client.post(VERIFY_URL, {'token': '000000'})
        self.assertContains(resp, 'Too many failed attempts')

    def test_already_verified_user_is_sent_on(self):
        self.mark_verified(self.device)
        resp = self.client.get(f'{VERIFY_URL}?next=/rocks/')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/rocks/')

    def test_user_without_device_is_sent_to_setup(self):
        other = User.objects.create_user(username='nodevice', password=PASSWORD)
        self.client.force_login(other)
        resp = self.client.get(VERIFY_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], SETUP_URL)

    def test_anonymous_user_is_sent_to_login(self):
        self.client.logout()
        resp = self.client.get(VERIFY_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/accounts/login/'))


class TwoFactorDisableTest(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.device = confirmed_totp_device(self.user)
        regenerate_backup_codes(self.user)
        self.login()

    def test_disable_requires_a_verified_session(self):
        resp = self.client.post(DISABLE_URL, {'password': PASSWORD})
        self.assertRedirectsToVerify(resp, DISABLE_URL)
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())

    def test_disable_requires_the_current_password(self):
        self.mark_verified(self.device)
        resp = self.client.post(DISABLE_URL, {'password': 'not-it'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/profile/')
        self.assertTrue(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertContains(self.client.get('/profile/'), 'was not disabled')

    def test_disable_is_post_only(self):
        self.mark_verified(self.device)
        self.assertEqual(self.client.get(DISABLE_URL).status_code, 405)

    def test_disable_removes_devices_and_stops_the_redirect(self):
        self.mark_verified(self.device)
        resp = self.client.post(DISABLE_URL, {'password': PASSWORD})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(TOTPDevice.objects.filter(user=self.user).exists())
        self.assertFalse(StaticDevice.objects.filter(user=self.user).exists())
        self.assertNotIn(DEVICE_ID_SESSION_KEY, self.client.session)

        self.client.logout()
        self.login()
        self.assertEqual(self.client.get('/rocks/').status_code, 200)
        self.assertContains(self.client.get('/profile/'), 'Not enabled')


class TwoFactorBackupCodesTest(TwoFactorTestCase):
    def setUp(self):
        super().setUp()
        self.device = confirmed_totp_device(self.user)
        self.old_codes = regenerate_backup_codes(self.user)
        self.login()

    def test_regenerate_requires_a_verified_session(self):
        resp = self.client.get(BACKUP_URL)
        self.assertRedirectsToVerify(resp, BACKUP_URL)

    def test_regenerate_requires_the_current_password(self):
        self.mark_verified(self.device)
        resp = self.client.post(BACKUP_URL, {'password': 'not-it'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'not correct')
        self.assertTrue(StaticToken.objects.filter(token=self.old_codes[0]).exists())

    def test_regenerate_replaces_codes_and_shows_them_once(self):
        self.mark_verified(self.device)
        page = self.client.get(BACKUP_URL)
        self.assertContains(page, '10</strong> unused backup codes')

        resp = self.client.post(BACKUP_URL, {'password': PASSWORD})
        self.assertEqual(resp.status_code, 200)
        new_codes = shown_backup_codes(resp)
        self.assertEqual(len(new_codes), 10)
        self.assertFalse(set(new_codes) & set(self.old_codes))
        self.assertEqual(stored_backup_codes(self.user), set(new_codes))

    def test_user_without_two_factor_is_sent_to_profile(self):
        other = User.objects.create_user(username='plain', password=PASSWORD)
        self.client.force_login(other)
        resp = self.client.get(BACKUP_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], '/profile/')


class ProfileTwoFactorCardTest(TwoFactorTestCase):
    def test_profile_offers_setup_when_not_enrolled(self):
        self.login()
        resp = self.client.get('/profile/')
        self.assertContains(resp, 'Not enabled')
        self.assertContains(resp, SETUP_URL)

    def test_profile_shows_status_and_disable_form_when_enrolled(self):
        device = confirmed_totp_device(self.user)
        regenerate_backup_codes(self.user)
        self.login()
        self.mark_verified(device)
        resp = self.client.get('/profile/')
        self.assertContains(resp, 'Enabled')
        self.assertContains(resp, device.created_at.strftime('%-d %b %Y'))
        self.assertContains(resp, '10 backup codes remaining')
        self.assertContains(resp, f'action="{DISABLE_URL}"')
        self.assertContains(resp, BACKUP_URL)
