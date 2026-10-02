from django.urls import path
from . import views

app_name = 'meetings'

urlpatterns = [
    path('', views.MeetingListView.as_view(), name='list'),
    path('create/', views.MeetingCreateView.as_view(), name='create'),
    path('<int:pk>/', views.MeetingDetailView.as_view(), name='detail'),
    path('<int:pk>/print/', views.MeetingPrintView.as_view(), name='print'),
    path('<int:pk>/start/', views.MeetingStartView.as_view(), name='start'),
    path('<int:pk>/advance/', views.MeetingAdvanceView.as_view(), name='advance'),
    path('<int:pk>/complete/', views.MeetingCompleteView.as_view(), name='complete'),
    path('<int:pk>/segue/', views.SegueAddView.as_view(), name='segue'),
    path('<int:pk>/headlines/add/', views.HeadlineAddView.as_view(), name='headline_add'),
    path('<int:pk>/headlines/<int:hpk>/escalate/', views.HeadlineEscalateView.as_view(), name='headline_escalate'),
    path('<int:pk>/rate/', views.MeetingRateView.as_view(), name='rate'),
    path('<int:pk>/notes/', views.MeetingNoteSaveView.as_view(), name='note_save'),
]
