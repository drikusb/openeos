from django import forms
from django.contrib.auth.models import User

from apps.accounts.models import Team
from .models import Scorecard, ScorecardMetric, ScorecardEntry


class ScorecardForm(forms.ModelForm):
    class Meta:
        model = Scorecard
        fields = ['name', 'description', 'team', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        teams = Team.objects.none()
        if organization:
            teams = Team.objects.filter(organization=organization).order_by('name')
        self.fields['team'].queryset = teams


class ScorecardMetricForm(forms.ModelForm):
    class Meta:
        model = ScorecardMetric
        fields = ['name', 'owner', 'metric_type', 'goal_value', 'goal_direction', 'frequency', 'order', 'is_active']
        widgets = {
            'goal_value': forms.NumberInput(attrs={'step': 'any'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        owners = User.objects.none()
        if organization:
            owners = (
                User.objects
                .filter(memberships__organization=organization)
                .order_by('first_name', 'last_name', 'username')
            )
        self.fields['owner'].queryset = owners
        self.fields['order'].initial = 0
        self.fields['is_active'].initial = True


class ScorecardEntryForm(forms.ModelForm):
    class Meta:
        model = ScorecardEntry
        fields = ['value', 'notes']
        widgets = {
            'value': forms.NumberInput(attrs={'step': 'any', 'class': 'form-control form-control-sm'}),
            'notes': forms.TextInput(attrs={'class': 'form-control form-control-sm',
                                           'placeholder': 'Optional note'}),
        }
