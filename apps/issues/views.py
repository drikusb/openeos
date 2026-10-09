from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.http import HttpResponseForbidden

from .models import Issue, IssueActivity
from .forms import IssueForm, IssueStatusForm, IssueDelegateForm, IssueCommentForm
from apps.accounts.scoping import (
    OrgScopedMixin, get_active_team, get_org_object_or_404, is_org_admin,
)

ISSUE_ORG_LOOKUP = 'originating_team__organization'


def _log(issue, actor, action, notes=''):
    IssueActivity.objects.create(issue=issue, actor=actor, action=action, notes=notes)


def _get_issue(request, pk):
    return get_org_object_or_404(request, Issue, org_lookup=ISSUE_ORG_LOOKUP, pk=pk)


def _can_edit(user, issue):
    return (
        user.profile.teams.filter(pk=issue.originating_team_id).exists()
        or is_org_admin(user, issue.originating_team.organization)
    )


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class IssueListView(LoginRequiredMixin, ListView):
    model = Issue
    template_name = 'issues/issue_list.html'
    context_object_name = 'issues'

    def get_queryset(self):
        team = get_active_team(self.request)
        if not team:
            return Issue.objects.none()
        qs = (
            Issue.objects
            .filter(originating_team=team)
            .select_related('originating_team', 'delegated_to_team', 'created_by', 'created_by__profile')
            .prefetch_related('linked_rocks')
        )
        # View filter: 'delegated' shows issues delegated TO the active team
        view = self.request.GET.get('view', '')
        if view == 'delegated':
            qs = Issue.objects.filter(delegated_to_team=team).select_related(
                'originating_team', 'delegated_to_team', 'created_by', 'created_by__profile'
            ).prefetch_related('linked_rocks')
        # Status filter
        status = self.request.GET.get('status', '')
        if status in dict(Issue.STATUS_CHOICES):
            qs = qs.filter(status=status)
        elif not status:
            qs = qs.filter(status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS])
        elif status == 'all':
            pass
        # Type filter
        issue_type = self.request.GET.get('type', '')
        if issue_type in dict(Issue.TYPE_CHOICES):
            qs = qs.filter(issue_type=issue_type)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update({
            'status_filter': self.request.GET.get('status', ''),
            'type_filter': self.request.GET.get('type', ''),
            'view_filter': self.request.GET.get('view', ''),
            'status_choices': Issue.STATUS_CHOICES,
            'type_choices': Issue.TYPE_CHOICES,
        })
        return ctx


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class IssueCreateView(LoginRequiredMixin, CreateView):
    model = Issue
    form_class = IssueForm
    template_name = 'issues/issue_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['team'] = get_active_team(self.request)
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.originating_team = get_active_team(self.request)
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        _log(self.object, self.request.user, IssueActivity.ACTION_CREATED)
        if self.object.is_delegated:
            _log(
                self.object, self.request.user, IssueActivity.ACTION_DELEGATED,
                notes=f'Delegated to {self.object.delegated_to_team.name} on creation.'
            )
        messages.success(self.request, f'Issue "{self.object.title}" created.')
        return response

    def get_success_url(self):
        return reverse('issues:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Create'
        return ctx


class IssueUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = Issue
    org_lookup = ISSUE_ORG_LOOKUP
    form_class = IssueForm
    template_name = 'issues/issue_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['team'] = self.get_object().originating_team
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f'Issue "{self.object.title}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class IssueDetailView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = Issue
    org_lookup = ISSUE_ORG_LOOKUP
    template_name = 'issues/issue_detail.html'
    context_object_name = 'issue'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        issue = self.object
        ctx['activity'] = issue.activity.select_related('actor', 'actor__profile').order_by('created_at')
        ctx['linked_rocks'] = issue.linked_rocks.select_related('team', 'owner')
        ctx['status_form'] = IssueStatusForm(initial={'status': issue.status, 'resolution_notes': issue.resolution_notes})
        ctx['delegate_form'] = IssueDelegateForm(
            initial={'delegated_to_team': issue.delegated_to_team},
            organization=issue.originating_team.organization,
        )
        ctx['comment_form'] = IssueCommentForm()
        ctx['can_edit'] = _can_edit(self.request.user, issue)
        return ctx


class IssueDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = Issue
    org_lookup = ISSUE_ORG_LOOKUP
    template_name = 'issues/issue_confirm_delete.html'
    success_url = reverse_lazy('issues:list')

    def form_valid(self, form):
        messages.success(self.request, f'Issue "{self.object.title}" deleted.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Status change
# ---------------------------------------------------------------------------

class IssueStatusView(LoginRequiredMixin, View):
    """POST-only: change an issue's status."""

    def post(self, request, pk):
        issue = _get_issue(request, pk)
        if not _can_edit(request.user, issue):
            return HttpResponseForbidden()
        form = IssueStatusForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            resolution_notes = form.cleaned_data.get('resolution_notes', '')
            old_status = issue.status
            issue.status = new_status
            if new_status == Issue.STATUS_RESOLVED and resolution_notes:
                issue.resolution_notes = resolution_notes
            issue.save(update_fields=['status', 'resolution_notes', 'updated_at'])

            action_map = {
                Issue.STATUS_RESOLVED: IssueActivity.ACTION_RESOLVED,
                Issue.STATUS_DROPPED: IssueActivity.ACTION_DROPPED,
            }
            action = action_map.get(new_status, IssueActivity.ACTION_STATUS_CHANGED)
            notes = resolution_notes or f'Status changed from {old_status} to {new_status}.'
            _log(issue, request.user, action, notes=notes)
        next_url = request.POST.get('next') or reverse('issues:detail', kwargs={'pk': pk})
        return redirect(next_url)


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------

class IssueDelegateView(LoginRequiredMixin, View):
    """POST-only: assign or recall delegation."""

    def post(self, request, pk):
        issue = _get_issue(request, pk)
        if not _can_edit(request.user, issue):
            return HttpResponseForbidden()
        form = IssueDelegateForm(
            request.POST, organization=issue.originating_team.organization
        )
        if form.is_valid():
            new_team = form.cleaned_data.get('delegated_to_team')
            if new_team:
                issue.delegated_to_team = new_team
                issue.save(update_fields=['delegated_to_team', 'updated_at'])
                _log(issue, request.user, IssueActivity.ACTION_DELEGATED,
                     notes=f'Delegated to {new_team.name}.')
                messages.success(request, f'Issue delegated to {new_team.name}.')
            else:
                # Recall delegation
                issue.delegated_to_team = None
                issue.save(update_fields=['delegated_to_team', 'updated_at'])
                _log(issue, request.user, IssueActivity.ACTION_RECALLED,
                     notes='Delegation recalled.')
                messages.success(request, 'Delegation recalled.')
        return redirect('issues:detail', pk=pk)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

class IssueCommentView(LoginRequiredMixin, View):
    """POST-only: add a comment to the activity log."""

    def post(self, request, pk):
        issue = _get_issue(request, pk)
        form = IssueCommentForm(request.POST)
        if form.is_valid():
            _log(issue, request.user, IssueActivity.ACTION_COMMENT,
                 notes=form.cleaned_data['notes'])
        return redirect('issues:detail', pk=pk)
