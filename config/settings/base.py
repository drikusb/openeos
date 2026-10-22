from pathlib import Path
from decouple import config, Csv

# /root/brains/eos
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config('SECRET_KEY', default='dev-secret-key-change-in-production-please')

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    # EOS modules — uncommented as each phase is built
    'apps.accounts',
    'apps.audit',
    'apps.rocks',
    'apps.issues',
    'apps.todos',
    'apps.scorecards',
    'apps.vto',
    'apps.accountability',
    'apps.meetings',
    'apps.notifications',
    # 'apps.todos',
    # 'apps.vto',
    # 'apps.scorecards',
    # 'apps.accountability',
    # 'apps.meetings',
]

# Deployments can enable third-party or private apps without forking, e.g.
# EXTRA_INSTALLED_APPS=django.contrib.sites,my_company.sso
INSTALLED_APPS += config('EXTRA_INSTALLED_APPS', default='', cast=Csv())

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'apps.accounts.middleware.OrganizationDomainMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'apps.accounts.two_factor.middleware.TwoFactorRequiredMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.accounts.context_processors.active_context',
                'apps.accounts.context_processors.branding',
                'apps.accounts.context_processors.terminology',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='eos_db'),
        'USER': config('DB_USER', default='eos_user'),
        'PASSWORD': config('DB_PASSWORD', default='eos_password'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'mediafiles'
# Avatars are served through a permission-checked view. When a proxy such as
# Nginx sits in front, let it send the bytes via X-Accel-Redirect instead of Django.
MEDIA_ACCEL_REDIRECT = config('MEDIA_ACCEL_REDIRECT', default=False, cast=bool)

# Largest organisation archive the browser export will build. Bigger ones are
# exported on the server with manage.py export_organization, which has no limit.
EXPORT_MAX_BYTES = config('EXPORT_MAX_BYTES', default=500 * 1024 * 1024, cast=int)

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# Shown as the account label in authenticator apps.
OTP_TOTP_ISSUER = config('OTP_TOTP_ISSUER', default='OpenEOS')

# ── Email ────────────────────────────────────────────────────────────────────
# Set EMAIL_HOST to enable SMTP; otherwise emails print to the console (dev-friendly default).
EMAIL_HOST = config('EMAIL_HOST', default='')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='EOS App <noreply@example.com>')

# Base URL used to build absolute links in emails (no trailing slash).
SITE_URL = config('SITE_URL', default='http://localhost:8000')

# Name shown in the navbar, page titles and emails when no organisation
# branding applies (the main host's login page, for instance).
DEFAULT_BRAND_NAME = config('BRAND_NAME', default='Empresadence')
