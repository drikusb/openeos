from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.test import SimpleTestCase


class StaticFilesStorageTest(SimpleTestCase):
    def test_whitenoise_manifest_storage_is_configured(self):
        self.assertEqual(
            settings.STORAGES['staticfiles']['BACKEND'],
            'whitenoise.storage.CompressedManifestStaticFilesStorage',
        )

    def test_whitenoise_manifest_storage_is_active(self):
        self.assertEqual(
            staticfiles_storage.__class__.__name__,
            'CompressedManifestStaticFilesStorage',
        )
