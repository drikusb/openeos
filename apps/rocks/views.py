from datetime import date
from itertools import groupby

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, FormView, View,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages
from django.http import HttpResponseForbidden

from .models import Rock, RockCheckin, RockDependency, RockMilestone
from .forms import RockForm, RockStatusForm, RockDependencyForm
from apps.accounts.scoping import (
    OrgScopedMixin, get_active_team, get_org_object_or_404, is_org_admin,
)
from apps.issues.models import Issue, IssueActivity


def get_quarter_year_from_request(request):
    try:
        quarter = int(request.GET.get('quarter', Rock.current_quarter()))
        year = int(request.GET.get('year', Rock.current_year()))
    except (ValueError, TypeError):
        quarter, year = Rock.current_quarter(), Rock.current_year()
    quarter = max(1, min(4, quarter))
    return quarter, year


def quarter_options(selected_q, selected_y):
    """Return 7 quarter options: 3 past, current, 3 future."""
    options = []
    q, y = Rock.current_quarter(), Rock.current_year()
    for _ in range(3):
        q, y = Rock.prev_quarter(q, y)
    for _ in range(7):
        options.append({
            'quarter': q, 'year': y,
            'label': f'Q{q} {y}',
            'selected': (q == selected_q and y == selected_y),
            'is_current': (q == Rock.current_quarter() and y == Rock.current_year()),
        })
        q, y = Rock.next_quarter(q, y)
    return options


def _can_edit(user, rock):
    """Only the owner or an organisation admin may change a Rock's status or check in."""
    return user == rock.owner or is_org_admin(user, rock.team.organization)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class RockListView(LoginRequiredMixin, ListView):
    model = Rock
    template_name = 'rocks/rock_list.html'
    context_object_name = 'rocks'

    def get_queryset(self):
        team = get_active_team(self.request)
        if not team:
            return Rock.objects.none()
        quarter, year = get_quarter_year_from_request(self.request)
        qs = (
            Rock.objects
            .filter(team=team, quarter=quarter, year=year)
            .select_related('owner', 'owner__profile', 'team')
            .order_by('owner__first_name', 'owner__username', 'title')
        )
        status = self.request.GET.get('status')
        if status in dict(Rock.STATUS_CHOICES):
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        quarter, year = get_quarter_year_from_request(self.request)
        ctx.update({
            'quarter': quarter,
            'year': year,
            'quarter_label': f'Q{quarter} {year}',
            'quarter_options': quarter_options(quarter, year),
            'prev_q': Rock.prev_quarter(quarter, year),
            'next_q': Rock.next_quarter(quarter, year),
            'status_filter': self.request.GET.get('status', ''),
            'status_choices': Rock.STATUS_CHOICES,
        })
        rocks = list(ctx['rocks'])
        ctx['teams_rocks'] = [(get_active_team(self.request), rocks)] if rocks else []
        ctx['my_rocks'] = [r for r in rocks if r.owner == self.request.user]
        return ctx


# ---------------------------------------------------------------------------
# Rock CRUD
# ---------------------------------------------------------------------------

class RockCreateView(LoginRequiredMixin, CreateView):
    model = Rock
    form_class = RockForm
    template_name = 'rocks/rock_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['team'] = get_active_team(self.request)
        return kwargs

    def form_valid(self, form):
        form.instance.team = get_active_team(self.request)
        form.instance.created_by = self.request.user
        messages.success(self.request, f'Rock "{form.instance.title}" created.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('rocks:detail', kwargs={'pk': self.object.pk})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Create'
        return ctx


class RockUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = Rock
    form_class = RockForm
    template_name = 'rocks/rock_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['team'] = self.get_object().team
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, f'Rock "{form.instance.title}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class RockDetailView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = Rock
    template_name = 'rocks/rock_detail.html'
    context_object_name = 'rock'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rock = self.object
        ctx['dependencies'] = (
            rock.dependencies.select_related('depends_on_rock', 'depends_on_rock__team', 'depends_on_rock__owner')
        )
        ctx['dependents'] = (
            rock.dependents.select_related('rock', 'rock__team', 'rock__owner')
        )
        ctx['child_rocks'] = rock.child_rocks.select_related('owner', 'team')
        ctx['dependency_form'] = RockDependencyForm(rock=rock)
        ctx['status_form'] = RockStatusForm(initial={'status': rock.status})
        ctx['can_edit'] = _can_edit(self.request.user, rock)
        ctx['today'] = date.today()
        ctx['linked_issues'] = rock.linked_issues.select_related(
            'originating_team', 'created_by'
        ).order_by('-created_at')
        ctx['linkable_issues'] = (
            Issue.objects
            .filter(originating_team=rock.team, status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS])
            .exclude(linked_rocks=rock)
            .order_by('-created_at')
        )
        ctx['checkins'] = rock.checkins.select_related('created_by')
        return ctx


class RockDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = Rock
    template_name = 'rocks/rock_confirm_delete.html'
    success_url = reverse_lazy('rocks:list')

    def form_valid(self, form):
        messages.success(self.request, f'Rock "{self.object.title}" deleted.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Status toggle
# ---------------------------------------------------------------------------

class RockStatusView(LoginRequiredMixin, View):
    """POST-only: update a Rock's status and redirect back."""

    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        form = RockStatusForm(request.POST)
        if form.is_valid():
            new_status = form.cleaned_data['status']
            if not _can_edit(request.user, rock):
                return HttpResponseForbidden()
            was_off_track = rock.status == Rock.STATUS_OFF_TRACK
            rock.status = new_status
            rock.save(update_fields=['status', 'updated_at'])
            if new_status == Rock.STATUS_OFF_TRACK and not was_off_track:
                from apps.notifications.emails import send_rock_off_track_alert
                send_rock_off_track_alert(rock)
        next_url = request.POST.get('next') or reverse('rocks:list')
        return redirect(next_url)


# ---------------------------------------------------------------------------
# Check-ins
# ---------------------------------------------------------------------------

class RockCheckinCreateView(LoginRequiredMixin, View):
    """POST-only: log a weekly progress check-in (owner or admin only)."""

    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        if not _can_edit(request.user, rock):
            return HttpResponseForbidden()

        confidence = request.POST.get('confidence')
        if confidence not in (Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK):
            messages.error(request, 'Please choose On Track or Off Track for the check-in.')
            return redirect('rocks:detail', pk=pk)

        RockCheckin.objects.create(
            rock=rock,
            confidence=confidence,
            note=request.POST.get('note', '').strip(),
            created_by=request.user,
        )
        messages.success(request, 'Check-in recorded.')
        return redirect('rocks:detail', pk=pk)


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

class RockArchiveView(LoginRequiredMixin, ListView):
    model = Rock
    template_name = 'rocks/rock_archive.html'
    context_object_name = 'rocks'

    def get_queryset(self):
        team = get_active_team(self.request)
        if not team:
            return Rock.objects.none()
        quarter, year = get_quarter_year_from_request(self.request)
        return (
            Rock.objects
            .filter(team=team, quarter=quarter, year=year)
            .select_related('owner', 'team')
            .order_by('status', 'title')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        quarter, year = get_quarter_year_from_request(self.request)
        rocks = list(ctx['rocks'])
        total = len(rocks)
        complete = sum(1 for r in rocks if r.is_complete())
        ctx.update({
            'quarter': quarter,
            'year': year,
            'quarter_label': f'Q{quarter} {year}',
            'quarter_options': quarter_options(quarter, year),
            'total': total,
            'complete': complete,
            'completion_pct': round(complete / total * 100) if total else 0,
            'teams_rocks': [
                (team, list(tr))
                for team, tr in groupby(rocks, key=lambda r: r.team)
            ],
        })
        return ctx


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

class RockDependencyCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        form = RockDependencyForm(request.POST, rock=rock)
        if form.is_valid():
            dep = form.save(commit=False)
            dep.rock = rock
            dep.save()
            messages.success(request, 'Dependency added.')
        else:
            messages.error(request, 'Could not add dependency. Please check your selection.')
        return redirect('rocks:detail', pk=pk)


class RockDependencyDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        dep = get_org_object_or_404(
            request, RockDependency, org_lookup='rock__team__organization', pk=pk
        )
        rock_pk = dep.rock.pk
        dep.delete()
        messages.success(request, 'Dependency removed.')
        return redirect('rocks:detail', pk=rock_pk)


# ---------------------------------------------------------------------------
# Milestones
# ---------------------------------------------------------------------------

def _get_milestone(request, pk):
    return get_org_object_or_404(
        request, RockMilestone, org_lookup='rock__team__organization', pk=pk
    )


class MilestoneCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        title = request.POST.get('title', '').strip()
        due_date = request.POST.get('due_date') or None
        description = request.POST.get('description', '').strip()
        if title:
            order = rock.milestones.count()
            RockMilestone.objects.create(
                rock=rock, title=title, due_date=due_date,
                description=description, order=order,
            )
            messages.success(request, 'Milestone added.')
        else:
            messages.error(request, 'Milestone title is required.')
        return redirect('rocks:detail', pk=pk)


class MilestoneEditView(LoginRequiredMixin, View):
    """GET renders an edit form; POST saves title/description/due_date."""

    def get(self, request, pk):
        milestone = _get_milestone(request, pk)
        return render(request, 'rocks/milestone_edit.html', {'milestone': milestone})

    def post(self, request, pk):
        milestone = _get_milestone(request, pk)
        title = request.POST.get('title', '').strip()
        if title:
            milestone.title = title
            milestone.description = request.POST.get('description', '').strip()
            milestone.due_date = request.POST.get('due_date') or None
            milestone.save(update_fields=['title', 'description', 'due_date'])
            messages.success(request, 'Milestone updated.')
        return redirect('rocks:detail', pk=milestone.rock_id)


class MilestoneToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        milestone = _get_milestone(request, pk)
        if milestone.is_complete:
            milestone.mark_open()
        else:
            milestone.mark_complete()
        return redirect('rocks:detail', pk=milestone.rock_id)


class MilestoneDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        milestone = _get_milestone(request, pk)
        rock_pk = milestone.rock_id
        milestone.delete()
        messages.success(request, 'Milestone removed.')
        return redirect('rocks:detail', pk=rock_pk)


# ---------------------------------------------------------------------------
# Rock ↔ Issue linking
# ---------------------------------------------------------------------------

class RockIssueLinkView(LoginRequiredMixin, View):
    """POST-only: add an Issue to a Rock's linked_issues M2M."""

    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        issue = get_object_or_404(
            Issue, pk=request.POST.get('issue_id'), originating_team=rock.team
        )
        rock.linked_issues.add(issue)
        IssueActivity.objects.create(
            issue=issue, actor=request.user,
            action=IssueActivity.ACTION_ROCK_LINKED,
            notes=f'Linked to Rock "{rock.title}".',
        )
        messages.success(request, f'Issue "{issue.title}" linked.')
        return redirect('rocks:detail', pk=pk)


class RockIssueUnlinkView(LoginRequiredMixin, View):
    """POST-only: remove an Issue from a Rock's linked_issues M2M."""

    def post(self, request, pk):
        rock = get_org_object_or_404(request, Rock, pk=pk)
        issue = get_object_or_404(rock.linked_issues, pk=request.POST.get('issue_id'))
        rock.linked_issues.remove(issue)
        IssueActivity.objects.create(
            issue=issue, actor=request.user,
            action=IssueActivity.ACTION_ROCK_UNLINKED,
            notes=f'Unlinked from Rock "{rock.title}".',
        )
        messages.success(request, f'Issue "{issue.title}" unlinked.')
        return redirect('rocks:detail', pk=pk)
