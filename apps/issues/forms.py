from django import forms

from apps.accounts.models import Team
from apps.accounts.scoping import is_org_admin
from apps.rocks.models import Rock
from .models import Issue, IssueActivity


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        # originating_team excluded: always set to the user's active team in the view
        fields = [
            'title', 'description', 'issue_type',
            'delegated_to_team',
            'linked_rocks',
            'target_quarter', 'target_year',
            'is_company_issue',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
            'target_year': forms.NumberInput(attrs={'min': 2020, 'max': 2099}),
            'is_company_issue': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, team=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Only an admin of the team's organisation may mark an Issue company-wide
        is_admin = bool(user) and is_org_admin(user, team.organization if team else None)
        if not is_admin:
            del self.fields['is_company_issue']
        if team:
            # Delegation can go to any team in the org
            org_teams = Team.objects.filter(organization=team.organization).order_by('name')
            self.fields['delegated_to_team'].queryset = org_teams
            self.fields['linked_rocks'].queryset = (
                Rock.objects
                .filter(team=team, status__in=[Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK])
                .select_related('owner')
                .order_by('title')
            )
        else:
            self.fields['delegated_to_team'].queryset = Team.objects.none()
            self.fields['linked_rocks'].queryset = Rock.objects.none()
        self.fields['delegated_to_team'].required = False
        self.fields['linked_rocks'].required = False
        self.fields['target_quarter'].required = False
        self.fields['target_year'].required = False

    def clean(self):
        cleaned_data = super().clean()
        issue_type = cleaned_data.get('issue_type')
        target_quarter = cleaned_data.get('target_quarter')
        target_year = cleaned_data.get('target_year')
        if issue_type == Issue.TYPE_LONG_TERM:
            if not target_quarter:
                self.add_error('target_quarter', 'Required for long-term issues.')
            if not target_year:
                self.add_error('target_year', 'Required for long-term issues.')
        elif 'is_company_issue' in cleaned_data:
            # Company-wide only means anything for long-term issues, the VTO only
            # ever shows those. Don't let a short-term issue carry the flag.
            cleaned_data['is_company_issue'] = False
        return cleaned_data


class IssueStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Issue.STATUS_CHOICES)
    resolution_notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False,
        max_length=2000,
    )

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        notes = cleaned_data.get('resolution_notes', '').strip()
        if status == Issue.STATUS_RESOLVED and not notes:
            self.add_error('resolution_notes', 'Please describe how this issue was resolved.')
        return cleaned_data


class IssueDelegateForm(forms.Form):
    delegated_to_team = forms.ModelChoiceField(
        queryset=Team.objects.none(),
        empty_label='— Remove delegation (recall) —',
        required=False,
        label='Delegate to team',
    )

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        teams = Team.objects.none()
        if organization:
            teams = Team.objects.filter(organization=organization).order_by('name')
        self.fields['delegated_to_team'].queryset = teams


class IssueCommentForm(forms.Form):
    notes = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2, 'placeholder': 'Add a comment…'}),
        max_length=2000,
        label='',
    )
