import importlib
import os

from django.test import SimpleTestCase

from config.settings import base


class ExtraInstalledAppsTest(SimpleTestCase):
    def setUp(self):
        self.original_env = os.environ.get('EXTRA_INSTALLED_APPS')
        self.original_apps = list(base.INSTALLED_APPS)

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop('EXTRA_INSTALLED_APPS', None)
        else:
            os.environ['EXTRA_INSTALLED_APPS'] = self.original_env
        importlib.reload(base)
        self.assertEqual(base.INSTALLED_APPS, self.original_apps)

    def test_apps_listed_in_the_environment_are_appended(self):
        os.environ['EXTRA_INSTALLED_APPS'] = 'django.contrib.sites'
        importlib.reload(base)
        self.assertIn('django.contrib.sites', base.INSTALLED_APPS)
        self.assertEqual(base.INSTALLED_APPS[-1], 'django.contrib.sites')

    def test_an_empty_value_adds_nothing(self):
        os.environ['EXTRA_INSTALLED_APPS'] = ''
        importlib.reload(base)
        self.assertEqual(base.INSTALLED_APPS, self.original_apps)
