from django.urls import path
from . import views

app_name = 'issues'

urlpatterns = [
    path('', views.IssueListView.as_view(), name='list'),
    path('export/', views.IssueCsvExportView.as_view(), name='export_csv'),
    path('new/', views.IssueCreateView.as_view(), name='create'),
    path('<int:pk>/', views.IssueDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.IssueUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.IssueDeleteView.as_view(), name='delete'),
    path('<int:pk>/status/', views.IssueStatusView.as_view(), name='status'),
    path('<int:pk>/delegate/', views.IssueDelegateView.as_view(), name='delegate'),
    path('<int:pk>/comment/', views.IssueCommentView.as_view(), name='comment'),
]
