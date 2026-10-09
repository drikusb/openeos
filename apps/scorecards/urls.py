from django.urls import path
from . import views

app_name = 'scorecards'

urlpatterns = [
    path('', views.ScorecardListView.as_view(), name='list'),
    path('new/', views.ScorecardCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ScorecardDetailView.as_view(), name='detail'),
    path('<int:pk>/export/', views.ScorecardCsvExportView.as_view(), name='export_csv'),
    path('<int:pk>/edit/', views.ScorecardUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.ScorecardDeleteView.as_view(), name='delete'),
    path('<int:pk>/enter/', views.ScorecardEntryView.as_view(), name='enter'),
    path('<int:scorecard_pk>/metrics/add/', views.MetricCreateView.as_view(), name='metric_add'),
    path('metric/<int:pk>/edit/', views.MetricUpdateView.as_view(), name='metric_edit'),
    path('metric/<int:pk>/delete/', views.MetricDeleteView.as_view(), name='metric_delete'),
    path('entry/<int:pk>/escalate/', views.MetricEscalateView.as_view(), name='entry_escalate'),
]
