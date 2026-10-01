from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, View
from django.shortcuts import redirect
from django.urls import reverse_lazy, reverse
from django.contrib import messages

from .models import Scorecard, ScorecardMetric, ScorecardEntry, _current_week_start, _current_month_start
from .forms import ScorecardForm, ScorecardMetricForm
from apps.accounts.scoping import (
    OrgScopedMixin, get_active_org, get_active_team, get_org_object_or_404,
)


def _build_periods(n=13, frequency='weekly'):
    """Return list of n period-start dates ending with the current period, oldest first."""
    if frequency == 'weekly':
        latest = _current_week_start()
        return [latest - timedelta(weeks=i) for i in range(n - 1, -1, -1)]
    latest = _current_month_start()
    periods = []
    y, m = latest.year, latest.month
    for _ in range(n):
        periods.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(periods))


# ---------------------------------------------------------------------------
# Scorecard CRUD
# ---------------------------------------------------------------------------

class ScorecardListView(LoginRequiredMixin, ListView):
    model = Scorecard
    template_name = 'scorecards/scorecard_list.html'
    context_object_name = 'scorecards'

    def get_queryset(self):
        team = get_active_team(self.request)
        if not team:
            return Scorecard.objects.none()
        return (
            Scorecard.objects
            .filter(team=team, is_active=True)
            .select_related('team')
            .prefetch_related('metrics')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        current_week = _current_week_start()

        # For each scorecard, attach a quick summary for the current week
        summaries = []
        for sc in ctx['scorecards']:
            metrics = list(sc.active_metrics)
            entries = {
                e.metric_id: e
                for e in ScorecardEntry.objects.filter(
                    metric__scorecard=sc,
                    period_start=current_week,
                )
            }
            on_track = sum(1 for m in metrics if entries.get(m.pk) and entries[m.pk].on_track)
            off_track = sum(1 for m in metrics if entries.get(m.pk) and not entries[m.pk].on_track)
            missing = sum(1 for m in metrics if m.pk not in entries)
            summaries.append({
                'scorecard': sc,
                'metrics': metrics,
                'entries': entries,
                'on_track': on_track,
                'off_track': off_track,
                'missing': missing,
                'total': len(metrics),
            })
        ctx['summaries'] = summaries
        ctx['current_week'] = current_week
        return ctx


class ScorecardCreateView(LoginRequiredMixin, CreateView):
    model = Scorecard
    form_class = ScorecardForm
    template_name = 'scorecards/scorecard_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = get_active_org(self.request)
        return kw

    def form_valid(self, form):
        messages.success(self.request, f'Scorecard "{form.instance.name}" created.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Create'
        return ctx


class ScorecardUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = Scorecard
    form_class = ScorecardForm
    template_name = 'scorecards/scorecard_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.object.team.organization
        return kw

    def form_valid(self, form):
        messages.success(self.request, f'Scorecard "{form.instance.name}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class ScorecardDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = Scorecard
    template_name = 'scorecards/scorecard_confirm_delete.html'
    success_url = reverse_lazy('scorecards:list')

    def form_valid(self, form):
        messages.success(self.request, f'Scorecard "{self.object.name}" deleted.')
        return super().form_valid(form)


# ---------------------------------------------------------------------------
# Scorecard detail — 13-week table
# ---------------------------------------------------------------------------

class ScorecardDetailView(LoginRequiredMixin, OrgScopedMixin, DetailView):
    model = Scorecard
    template_name = 'scorecards/scorecard_detail.html'
    context_object_name = 'scorecard'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        sc = self.object
        metrics = list(sc.active_metrics.select_related('owner', 'owner__profile'))
        current_week = _current_week_start()

        # Build 13 weekly periods (oldest → newest)
        periods = _build_periods(13, 'weekly')

        # Fetch all entries in range for this scorecard
        entry_map = {
            (e.metric_id, e.period_start): e
            for e in ScorecardEntry.objects.filter(
                metric__scorecard=sc,
                period_start__gte=periods[0],
                period_start__lte=periods[-1],
            ).select_related('entered_by')
        }

        # Build table rows: [{metric, cells: [entry|None, ...]}]
        table = []
        for m in metrics:
            cells = [entry_map.get((m.pk, p)) for p in periods]
            table.append({'metric': m, 'cells': cells})

        ctx['periods'] = periods
        ctx['table'] = table
        ctx['current_week'] = current_week
        ctx['metric_form'] = ScorecardMetricForm(organization=sc.team.organization)
        return ctx


# ---------------------------------------------------------------------------
# Metric CRUD
# ---------------------------------------------------------------------------

class MetricCreateView(LoginRequiredMixin, CreateView):
    model = ScorecardMetric
    form_class = ScorecardMetricForm
    template_name = 'scorecards/metric_form.html'

    def get_scorecard(self):
        return get_org_object_or_404(self.request, Scorecard, pk=self.kwargs['scorecard_pk'])

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.get_scorecard().team.organization
        return kw

    def form_valid(self, form):
        form.instance.scorecard = self.get_scorecard()
        messages.success(self.request, f'Metric "{form.instance.name}" added.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('scorecards:detail', kwargs={'pk': self.kwargs['scorecard_pk']})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['scorecard'] = self.get_scorecard()
        ctx['action'] = 'Add'
        return ctx


class MetricUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = ScorecardMetric
    org_lookup = 'scorecard__team__organization'
    form_class = ScorecardMetricForm
    template_name = 'scorecards/metric_form.html'

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['organization'] = self.object.scorecard.team.organization
        return kw

    def form_valid(self, form):
        messages.success(self.request, f'Metric "{form.instance.name}" updated.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('scorecards:detail', kwargs={'pk': self.object.scorecard_id})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['scorecard'] = self.object.scorecard
        ctx['action'] = 'Edit'
        return ctx


class MetricDeleteView(LoginRequiredMixin, View):
    """Soft-delete a metric (sets is_active=False)."""

    def post(self, request, pk):
        metric = get_org_object_or_404(
            request, ScorecardMetric, org_lookup='scorecard__team__organization', pk=pk
        )
        scorecard_pk = metric.scorecard_id
        metric.is_active = False
        metric.save(update_fields=['is_active'])
        messages.success(request, f'Metric "{metric.name}" removed.')
        return redirect('scorecards:detail', pk=scorecard_pk)


# ---------------------------------------------------------------------------
# Weekly entry — POST multiple values in one form
# ---------------------------------------------------------------------------

class ScorecardEntryView(LoginRequiredMixin, View):
    """GET: show entry form for current period. POST: save/update entries."""

    template_name = 'scorecards/entry_form.html'

    def _get_data(self, scorecard):
        metrics = list(scorecard.active_metrics.select_related('owner'))
        current_week = _current_week_start()
        existing = {
            e.metric_id: e
            for e in ScorecardEntry.objects.filter(
                metric__scorecard=scorecard,
                period_start=current_week,
            )
        }
        return metrics, current_week, existing

    def get(self, request, pk):
        scorecard = get_org_object_or_404(request, Scorecard, pk=pk)
        metrics, current_week, existing = self._get_data(scorecard)
        return self._render(request, scorecard, metrics, current_week, existing, errors={})

    def post(self, request, pk):
        scorecard = get_org_object_or_404(request, Scorecard, pk=pk)
        metrics, current_week, existing = self._get_data(scorecard)
        errors = {}
        saved = 0

        for metric in metrics:
            raw = request.POST.get(f'value_{metric.pk}', '').strip()
            notes = request.POST.get(f'notes_{metric.pk}', '').strip()
            if not raw:
                continue  # skip blanks — don't delete existing
            try:
                value = Decimal(raw)
            except InvalidOperation:
                errors[metric.pk] = 'Invalid number.'
                continue

            entry = existing.get(metric.pk)
            if entry:
                entry.value = value
                entry.notes = notes
                entry.entered_by = request.user
                entry.save()
            else:
                ScorecardEntry.objects.create(
                    metric=metric,
                    period_start=current_week,
                    value=value,
                    notes=notes,
                    entered_by=request.user,
                )
            saved += 1

        if errors:
            return self._render(request, scorecard, metrics, current_week, existing, errors=errors)

        messages.success(request, f'{saved} metric{"s" if saved != 1 else ""} updated for week of {current_week}.')
        return redirect('scorecards:detail', pk=pk)

    def _render(self, request, scorecard, metrics, current_week, existing, errors):
        from django.shortcuts import render
        rows = []
        for m in metrics:
            entry = existing.get(m.pk)
            rows.append({
                'metric': m,
                'entry': entry,
                'error': errors.get(m.pk),
                'value_str': str(entry.value) if entry else '',
            })
        return render(request, self.template_name, {
            'scorecard': scorecard,
            'rows': rows,
            'current_week': current_week,
            'period_label': f'Week of {current_week.strftime("%b %d, %Y")}',
        })


# ---------------------------------------------------------------------------
# Escalate off-track metric to Issue
# ---------------------------------------------------------------------------

class MetricEscalateView(LoginRequiredMixin, View):
    """POST-only: create an Issue from an off-track metric entry."""

    def post(self, request, pk):
        entry = get_org_object_or_404(
            request, ScorecardEntry,
            org_lookup='metric__scorecard__team__organization', pk=pk,
        )
        metric = entry.metric

        from apps.issues.models import Issue, IssueActivity
        issue = Issue.objects.create(
            title=f'Off-track: {metric.name}',
            description=(
                f'Metric "{metric.name}" on {metric.scorecard.name} was off-track '
                f'for the week of {entry.period_start}.\n\n'
                f'Value: {metric.format_value(entry.value)} '
                f'(goal: {metric.format_goal()})\n'
                f'{("Notes: " + entry.notes) if entry.notes else ""}'
            ),
            originating_team=metric.scorecard.team,
            created_by=request.user,
            issue_type=Issue.TYPE_SHORT_TERM,
            status=Issue.STATUS_OPEN,
        )
        IssueActivity.objects.create(
            issue=issue,
            actor=request.user,
            action=IssueActivity.ACTION_CREATED,
            notes=f'Created from off-track Scorecard metric "{metric.name}".',
        )
        messages.success(request, f'Issue created for off-track metric "{metric.name}".')
        return redirect('issues:detail', pk=issue.pk)
