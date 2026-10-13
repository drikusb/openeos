from django.urls import path

from . import views

app_name = 'audit'

urlpatterns = [
    path('org/audit/', views.AuditEventListView.as_view(), name='event_list'),
]
