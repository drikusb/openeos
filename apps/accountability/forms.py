from django import forms
from django.contrib.auth.models import User

from .models import AccountabilityNode, AccountabilityRole


class NodeForm(forms.ModelForm):
    class Meta:
        model = AccountabilityNode
        fields = ['name', 'node_type', 'owner', 'order']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Visionary, Marketing Lead, Operations Manager',
            }),
            'node_type': forms.Select(attrs={'class': 'form-select'}),
            'owner': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['owner'].required = False
        self.fields['owner'].empty_label = '— Vacant —'
        owners = User.objects.none()
        if org:
            owners = (
                User.objects
                .filter(memberships__organization=org)
                .order_by('first_name', 'last_name', 'username')
            )
        self.fields['owner'].queryset = owners


class RoleForm(forms.ModelForm):
    class Meta:
        model = AccountabilityRole
        fields = ['description', 'order']
        widgets = {
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. Own the P&L, Drive revenue, Hire and fire the team',
            }),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }
