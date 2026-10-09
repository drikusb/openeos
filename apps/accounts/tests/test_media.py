import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import Resolver404, resolve

from apps.accounts.models import Membership
from apps.accounts.tests.test_isolation import build_org
from apps.accounts.views import MediaAvatarView

TEMP_MEDIA_ROOT = tempfile.mkdtemp()
AVATAR_BYTES = b'\x89PNG\r\n\x1a\n alpha avatar bytes'


@override_settings(MEDIA_ROOT=TEMP_MEDIA_ROOT, MEDIA_ACCEL_REDIRECT=False)
class MediaAvatarViewTest(TestCase):
    """Avatars are only served to the owner, a superuser, or a member of a shared organisation.

    Outsiders get 404 rather than 403, matching the rest of the organisation
    isolation (``get_org_object_or_404``): a 403 would confirm that a guessed
    file name belongs to a real user, and the name is the only secret here.
    """

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA_ROOT, ignore_errors=True)

    def setUp(self):
        self.alpha = build_org('Alpha')
        self.beta = build_org('Beta')
        self.owner = self.alpha['user']
        profile = self.owner.profile
        profile.avatar = SimpleUploadedFile('alpha.png', AVATAR_BYTES, content_type='image/png')
        profile.save()
        self.file_name = profile.avatar.name.removeprefix('avatars/')
        self.url = f'/media/avatars/{self.file_name}'

        self.colleague = User.objects.create_user(username='alphacolleague', password='pw')
        Membership.objects.create(user=self.colleague, organization=self.alpha['org'])
        self.outsider = self.beta['user']
        self.superuser = User.objects.create_superuser(username='root', password='pw')

    def assert_serves_avatar(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), AVATAR_BYTES)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('private', response['Cache-Control'])

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response, f'/accounts/login/?next={self.url}', fetch_redirect_response=False,
        )

    def test_owner_gets_the_file(self):
        self.client.force_login(self.owner)
        self.assert_serves_avatar(self.client.get(self.url))

    def test_member_of_same_organisation_gets_the_file(self):
        self.client.force_login(self.colleague)
        self.assert_serves_avatar(self.client.get(self.url))

    def test_member_of_other_organisation_gets_404(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_superuser_gets_the_file(self):
        self.client.force_login(self.superuser)
        self.assert_serves_avatar(self.client.get(self.url))

    def test_unknown_file_gets_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/media/avatars/nobody.png').status_code, 404)

    def test_path_traversal_gets_404(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/media/avatars/..%2F..%2Fsettings.py')
        self.assertEqual(response.status_code, 404)
        response = self.client.get(f'/media/avatars/..%2Favatars%2F{self.file_name}')
        self.assertEqual(response.status_code, 404)

    @override_settings(MEDIA_ACCEL_REDIRECT=True)
    def test_accel_redirect_hands_the_file_to_the_proxy(self):
        self.client.force_login(self.colleague)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'')
        self.assertEqual(
            response['X-Accel-Redirect'], f'/_protected_media/avatars/{self.file_name}',
        )
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('private', response['Cache-Control'])

    @override_settings(MEDIA_ACCEL_REDIRECT=True)
    def test_accel_redirect_still_refuses_outsiders(self):
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn('X-Accel-Redirect', response)

    def test_avatar_urls_resolve_to_the_view(self):
        match = resolve(self.url)
        self.assertIs(match.func.view_class, MediaAvatarView)
        self.assertEqual(match.kwargs, {'name': self.file_name})

    def test_organisation_logos_are_not_claimed_by_the_view(self):
        try:
            match = resolve('/media/org_logos/logo.png')
        except Resolver404:
            return
        self.assertIsNot(getattr(match.func, 'view_class', None), MediaAvatarView)
