from django.urls import path
from . import views

app_name = 'rocks'

urlpatterns = [
    path('', views.RockListView.as_view(), name='list'),
    path('new/', views.RockCreateView.as_view(), name='create'),
    path('archive/', views.RockArchiveView.as_view(), name='archive'),
    path('export/', views.RockCsvExportView.as_view(), name='export_csv'),
    path('<int:pk>/', views.RockDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.RockUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.RockDeleteView.as_view(), name='delete'),
    path('<int:pk>/status/', views.RockStatusView.as_view(), name='status'),
    path('<int:pk>/checkins/add/', views.RockCheckinCreateView.as_view(), name='checkin_add'),
    path('<int:pk>/dependency/add/', views.RockDependencyCreateView.as_view(), name='dependency_add'),
    path('dependency/<int:pk>/remove/', views.RockDependencyDeleteView.as_view(), name='dependency_remove'),
    path('<int:pk>/milestones/add/', views.MilestoneCreateView.as_view(), name='milestone_add'),
    path('milestones/<int:pk>/toggle/', views.MilestoneToggleView.as_view(), name='milestone_toggle'),
    path('milestones/<int:pk>/edit/', views.MilestoneEditView.as_view(), name='milestone_edit'),
    path('milestones/<int:pk>/delete/', views.MilestoneDeleteView.as_view(), name='milestone_delete'),
    path('<int:pk>/issues/link/', views.RockIssueLinkView.as_view(), name='issue_link'),
    path('<int:pk>/issues/unlink/', views.RockIssueUnlinkView.as_view(), name='issue_unlink'),
]
