import csv
from datetime import date
from itertools import groupby

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, FormView, View,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.utils.http import urlencode
from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponseForbidden, HttpResponse

from .models import Rock, RockCheckin, RockDependency, RockMilestone
from .forms import RockForm, RockStatusForm, RockDependencyForm
from apps.accounts.scoping import (
    OrgScopedMixin, get_active_org, get_active_team, get_assignable_teams,
    get_org_object_or_404, is_org_admin,
)
from apps.accounts.terminology import get_terms
from apps.issues.models import Issue, IssueActivity

SCOPE_SESSION_KEY = 'rocks_scope'
SCOPE_TEAM = 'team'
SCOPE_ALL = 'all'
SCOPES = (SCOPE_TEAM, SCOPE_ALL)


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


def get_rocks_scope(request):
    """Return the list scope: ``'team'`` (the navbar's active team) or ``'all'``.

    ``?scope=`` switches it and the choice is kept in the session, so the
    quarter and status links, which carry no scope, keep showing the same
    teams. Anything else in ``?scope=`` is ignored in favour of the session.
    """
    scope = request.GET.get('scope')
    if scope in SCOPES:
        request.session[SCOPE_SESSION_KEY] = scope
        return scope
    scope = request.session.get(SCOPE_SESSION_KEY)
    return scope if scope in SCOPES else SCOPE_TEAM


def get_visible_teams(request):
    """Teams whose Rocks the user may list: their own, or every team for an org admin."""
    return get_assignable_teams(request.user, get_active_org(request))


def scoped_rocks(request, quarter, year):
    """Rocks for the quarter in the teams the current scope covers, ordered for grouping."""
    if get_rocks_scope(request) == SCOPE_ALL:
        team_filter = {'team__in': get_visible_teams(request)}
    else:
        team = get_active_team(request)
        if team is None:
            return Rock.objects.none()
        team_filter = {'team': team}
    return (
        Rock.objects
        .filter(quarter=quarter, year=year, **team_filter)
        .select_related('owner', 'owner__profile', 'team')
        .order_by('team__name', 'owner__first_name', 'owner__username', 'title')
    )


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

    def _status_filter(self):
        status = self.request.GET.get('status')
        return status if status in dict(Rock.STATUS_CHOICES) else None

    def get_queryset(self):
        quarter, year = get_quarter_year_from_request(self.request)
        qs = scoped_rocks(self.request, quarter, year)
        status = self._status_filter()
        if status:
            qs = qs.filter(status=status)
        return qs

    def _other_team_counts(self, team, visible_teams, quarter, year):
        """How many matching Rocks the user's other visible teams have this quarter."""
        others = (
            Rock.objects
            .filter(quarter=quarter, year=year, team__in=visible_teams)
            .exclude(team=team)
        )
        status = self._status_filter()
        if status:
            others = others.filter(status=status)
        counts = dict(others.values('team').annotate(n=Count('id')).values_list('team', 'n'))
        return [(t, counts[t.pk]) for t in visible_teams if t.pk in counts]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        quarter, year = get_quarter_year_from_request(self.request)
        scope = get_rocks_scope(self.request)
        status = self._status_filter()
        # Quarter and status, for links that switch scope without losing the filters.
        filter_query = urlencode(
            {'quarter': quarter, 'year': year, **({'status': status} if status else {})}
        )
        active_team = get_active_team(self.request)
        visible_teams = list(get_visible_teams(self.request))
        other_team_counts = []
        if scope == SCOPE_ALL:
            scoped_teams = visible_teams
        else:
            scoped_teams = [active_team] if active_team else []
            if active_team:
                other_team_counts = self._other_team_counts(
                    active_team, visible_teams, quarter, year
                )
        ctx.update({
            'quarter': quarter,
            'year': year,
            'quarter_label': f'Q{quarter} {year}',
            'quarter_options': quarter_options(quarter, year),
            'prev_q': Rock.prev_quarter(quarter, year),
            'next_q': Rock.next_quarter(quarter, year),
            'status_filter': self.request.GET.get('status', ''),
            'status_choices': Rock.STATUS_CHOICES,
            'scope': scope,
            'filter_query': filter_query,
            'active_team': active_team,
            'visible_teams': visible_teams,
            'scoped_teams': scoped_teams,
            'other_team_counts': other_team_counts,
            'other_rocks_total': sum(n for _, n in other_team_counts),
            'other_teams_summary': ', '.join(f'{t.name}: {n}' for t, n in other_team_counts),
        })
        rocks = list(ctx['rocks'])
        ctx['teams_rocks'] = [
            (team, list(team_rocks))
            for team, team_rocks in groupby(rocks, key=lambda r: r.team)
        ]
        ctx['my_rocks'] = [r for r in rocks if r.owner == self.request.user]
        return ctx


class RockCsvExportView(LoginRequiredMixin, View):
    """GET-only: export the rocks in the current scope for the requested quarter as CSV.

    The scope is the same one the list uses (see ``get_rocks_scope``): the
    active team by default, or every team the user may see.
    """

    def get(self, request):
        quarter, year = get_quarter_year_from_request(request)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="rocks_q{quarter}_{year}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Title', 'Team', 'Owner', 'Status', 'Quarter', 'Year', 'Due Date'])
        for rock in scoped_rocks(request, quarter, year):
            owner_name = rock.owner.get_full_name() or rock.owner.username
            writer.writerow([
                rock.title, rock.team.name, owner_name, rock.get_status_display(),
                rock.quarter, rock.year, rock.due_date.isoformat(),
            ])
        return response


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
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.team = get_active_team(self.request)
        form.instance.created_by = self.request.user
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.rock} "{form.instance.title}" created.')
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
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.rock} "{form.instance.title}" updated.')
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
        terms = get_terms(self.request)
        messages.success(self.request, f'{terms.rock} "{self.object.title}" deleted.')
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
        terms = get_terms(request)
        if title:
            order = rock.milestones.count()
            RockMilestone.objects.create(
                rock=rock, title=title, due_date=due_date,
                description=description, order=order,
            )
            messages.success(request, f'{terms.milestone} added.')
        else:
            messages.error(request, f'{terms.milestone} title is required.')
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
            messages.success(request, f'{get_terms(request).milestone} updated.')
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
        messages.success(request, f'{get_terms(request).milestone} removed.')
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
        messages.success(request, f'{get_terms(request).issue} "{issue.title}" linked.')
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
        messages.success(request, f'{get_terms(request).issue} "{issue.title}" unlinked.')
        return redirect('rocks:detail', pk=pk)
