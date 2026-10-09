from django.urls import path

from . import views

# Included under the ``accounts`` namespace at accounts/2fa/.
urlpatterns = [
    path('setup/', views.TwoFactorSetupView.as_view(), name='two_factor_setup'),
    path('verify/', views.TwoFactorVerifyView.as_view(), name='two_factor_verify'),
    path('disable/', views.TwoFactorDisableView.as_view(), name='two_factor_disable'),
    path(
        'backup-codes/',
        views.TwoFactorBackupCodesView.as_view(),
        name='two_factor_backup_codes',
    ),
]
