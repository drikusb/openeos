from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from apps.accounts.views import HealthzView, HomeView

urlpatterns = [
    path('healthz/', HealthzView.as_view(), name='healthz'),
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('apps.accounts.urls', namespace='accounts')),
    path('rocks/', include('apps.rocks.urls', namespace='rocks')),
    path('issues/', include('apps.issues.urls', namespace='issues')),
    path('todos/', include('apps.todos.urls', namespace='todos')),
    path('scorecards/', include('apps.scorecards.urls', namespace='scorecards')),
    path('vto/', include('apps.vto.urls', namespace='vto')),
    path('accountability/', include('apps.accountability.urls', namespace='accountability')),
    path('meetings/', include('apps.meetings.urls', namespace='meetings')),
    path('notifications/', include('apps.notifications.urls', namespace='notifications')),
    path('', HomeView.as_view(), name='home'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
