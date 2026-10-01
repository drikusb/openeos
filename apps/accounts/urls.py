from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('org/setup/', views.OrgSetupView.as_view(), name='org_setup'),
    path('org/', views.OrgDetailView.as_view(), name='org_detail'),
    path('org/<int:pk>/switch/', views.OrgSwitchView.as_view(), name='org_switch'),
    path('teams/', views.TeamListView.as_view(), name='team_list'),
    path('teams/new/', views.TeamCreateView.as_view(), name='team_create'),
    path('teams/<int:pk>/', views.TeamDetailView.as_view(), name='team_detail'),
    path('teams/<int:pk>/edit/', views.TeamUpdateView.as_view(), name='team_update'),
    path('teams/<int:pk>/members/', views.TeamMembersUpdateView.as_view(), name='team_members'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/invite/', views.UserInviteView.as_view(), name='user_invite'),
    path('teams/<int:pk>/switch/', views.TeamSwitchView.as_view(), name='team_switch'),
    path('search/', views.SearchView.as_view(), name='search'),
]
