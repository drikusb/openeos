from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, ListView
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.db.models import Q

from .models import Meeting, MeetingNote, SegueEntry, Headline, MeetingRating, SEGMENT_NAMES, SEGMENT_DURATIONS, SEGMENT_TEMPLATES
from .forms import MeetingCreateForm, SegueEntryForm, HeadlineForm, MeetingRatingForm, CascadingMessagesForm
from apps.accounts.scoping import get_active_org, get_active_team


def _get_org(request):
    return get_active_org(request)


def _team_member_user_ids(team):
    return list(team.members.values_list('user_id', flat=True))


def _build_runner_context(meeting, user):
    """Build full context dict for the meeting runner view."""
    team = meeting.team

    # Scorecards
    from apps.scorecards.models import Scorecard, ScorecardEntry, _current_week_start
    scorecards = list(
        Scorecard.objects
        .filter(team=team, is_active=True)
        .prefetch_related('metrics')
    )
    week_start = _current_week_start()
    week_entries = {
        e.metric_id: e
        for e in ScorecardEntry.objects.filter(
            metric__scorecard__team=team,
            period_start=week_start,
        ).select_related('metric')
    }

    # Rocks
    from apps.rocks.models import Rock
    q, y = Rock.current_quarter(), Rock.current_year()
    rocks = list(
        Rock.objects
        .filter(team=team, quarter=q, year=y,
                status__in=[Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK])
        .select_related('owner')
        .order_by('status', 'title')
    )

    # Issues (open, for this team)
    from apps.issues.models import Issue
    issues = list(
        Issue.objects
        .filter(
            Q(originating_team=team) | Q(delegated_to_team=team),
            status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS],
        )
        .select_related('originating_team')
        .order_by('issue_type', 'created_at')
    )

    # Open To-Dos for team members
    from apps.todos.models import ToDo
    member_ids = _team_member_user_ids(team)
    todos = list(
        ToDo.objects
        .filter(owner_id__in=member_ids, status=ToDo.STATUS_OPEN)
        .select_related('owner')
        .order_by('due_date', 'created_at')
    )

    # Segue entries
    segue_entries = list(meeting.segue_entries.select_related('participant').all())
    my_segue = next((e for e in segue_entries if e.participant_id == user.pk), None)

    # Headlines
    headlines = list(meeting.headlines.select_related('author', 'escalated_issue').all())

    # Ratings
    ratings = list(meeting.ratings.select_related('participant').all())
    my_rating = next((r for r in ratings if r.participant_id == user.pk), None)
    avg_rating = None
    if ratings:
        avg_rating = round(sum(r.score for r in ratings) / len(ratings), 1)

    # To-Dos created during this meeting
    new_todos = []
    if meeting.started_at:
        new_todos = list(
            ToDo.objects
            .filter(owner_id__in=member_ids, created_at__gte=meeting.started_at)
            .select_related('owner')
            .order_by('created_at')
        )

    # Notes
    all_notes = {n.segment: n for n in meeting.notes.select_related('updated_by').all()}
    current_note = all_notes.get(meeting.current_segment)
    segment_notes = [
        all_notes[i] for i in range(len(SEGMENT_NAMES)) if i in all_notes
    ]

    return {
        'meeting': meeting,
        'team': team,
        'segment_idx': meeting.current_segment,
        'segment_name': SEGMENT_NAMES[meeting.current_segment],
        'segment_duration': SEGMENT_DURATIONS[meeting.current_segment],
        'segment_template': f"meetings/segments/{SEGMENT_TEMPLATES[meeting.current_segment]}",
        'is_last_segment': meeting.is_last_segment,
        'segments': list(enumerate(zip(SEGMENT_NAMES, SEGMENT_DURATIONS))),
        'current_note': current_note,
        'segment_notes': segment_notes,
        # Segment data
        'scorecards': scorecards,
        'week_entries': week_entries,
        'rocks': rocks,
        'rock_quarter': f'Q{q} {y}',
        'issues': issues,
        'todos': todos,
        'segue_entries': segue_entries,
        'my_segue': my_segue,
        'segue_form': SegueEntryForm(instance=my_segue),
        'headlines': headlines,
        'headline_form': HeadlineForm(),
        'ratings': ratings,
        'my_rating': my_rating,
        'rating_form': MeetingRatingForm(instance=my_rating),
        'cascading_form': CascadingMessagesForm(instance=meeting),
        'avg_rating': avg_rating,
        'new_todos': new_todos,
    }


# ---------------------------------------------------------------------------
# Meeting list / create
# ---------------------------------------------------------------------------

class MeetingListView(LoginRequiredMixin, View):
    template_name = 'meetings/meeting_list.html'

    def get(self, request):
        team = get_active_team(request)
        if not team:
            messages.warning(request, 'Join a team to see meetings.')
            return redirect('home')
        meetings = (
            Meeting.objects
            .filter(team=team)
            .select_related('team')
            .order_by('-scheduled_date')
        )
        return render(request, self.template_name, {'meetings': meetings, 'org': team.organization})


class MeetingCreateView(LoginRequiredMixin, View):
    template_name = 'meetings/meeting_form.html'

    def get(self, request):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        form = MeetingCreateForm(org=org)
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        form = MeetingCreateForm(request.POST, org=org)
        if form.is_valid():
            meeting = form.save(commit=False)
            meeting.created_by = request.user
            meeting.save()
            messages.success(request, f'Meeting scheduled for {meeting.scheduled_date}.')
            return redirect('meetings:detail', pk=meeting.pk)
        return render(request, self.template_name, {'form': form})


# ---------------------------------------------------------------------------
# Meeting runner
# ---------------------------------------------------------------------------

class MeetingDetailView(LoginRequiredMixin, View):
    template_name = 'meetings/meeting_detail.html'

    def _get_meeting(self, request, pk):
        org = _get_org(request)
        if not org:
            return None, None
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        return meeting, org

    def get(self, request, pk):
        meeting, org = self._get_meeting(request, pk)
        if not org:
            return redirect('accounts:org_setup')
        ctx = _build_runner_context(meeting, request.user)
        return render(request, self.template_name, ctx)


class MeetingStartView(LoginRequiredMixin, View):
    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        if meeting.is_scheduled:
            meeting.start()
            messages.success(request, 'Meeting started! Good luck — you\'ve got 90 minutes.')
        return redirect('meetings:detail', pk=pk)


class MeetingAdvanceView(LoginRequiredMixin, View):
    """Advance to the next segment."""

    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        if meeting.is_active and not meeting.is_last_segment:
            meeting.advance()
        return redirect('meetings:detail', pk=pk)


class MeetingCompleteView(LoginRequiredMixin, View):
    """Save cascading messages and mark complete."""

    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        if meeting.is_active:
            cascading = request.POST.get('cascading_messages', '')
            meeting.complete(cascading_messages=cascading)
            messages.success(request, 'Meeting completed! Great work.')
        return redirect('meetings:detail', pk=pk)


# ---------------------------------------------------------------------------
# Segue
# ---------------------------------------------------------------------------

class SegueAddView(LoginRequiredMixin, View):
    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        entry, _ = SegueEntry.objects.get_or_create(meeting=meeting, participant=request.user)
        form = SegueEntryForm(request.POST, instance=entry)
        if form.is_valid():
            form.save()
            messages.success(request, 'Segue entry saved.')
        return redirect('meetings:detail', pk=pk)


# ---------------------------------------------------------------------------
# Headlines
# ---------------------------------------------------------------------------

class HeadlineAddView(LoginRequiredMixin, View):
    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        form = HeadlineForm(request.POST)
        if form.is_valid():
            h = form.save(commit=False)
            h.meeting = meeting
            h.author = request.user
            h.save()
            messages.success(request, 'Headline added.')
        return redirect('meetings:detail', pk=pk)


class HeadlineEscalateView(LoginRequiredMixin, View):
    def post(self, request, pk, hpk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        headline = get_object_or_404(Headline, pk=hpk, meeting=meeting)
        if not headline.escalated_issue:
            from apps.issues.models import Issue, IssueActivity
            issue = Issue.objects.create(
                title=headline.text[:150],
                originating_team=meeting.team,
                issue_type=Issue.TYPE_SHORT_TERM,
                created_by=headline.author or request.user,
                status=Issue.STATUS_OPEN,
            )
            IssueActivity.objects.create(
                issue=issue,
                actor=request.user,
                action=IssueActivity.ACTION_CREATED,
                notes=f'Escalated from Level 10 Meeting headline on {meeting.scheduled_date}',
            )
            headline.escalated_issue = issue
            headline.save(update_fields=['escalated_issue'])
            messages.success(request, 'Headline escalated to Issues.')
        return redirect('meetings:detail', pk=pk)


# ---------------------------------------------------------------------------
# Rating
# ---------------------------------------------------------------------------

class MeetingRateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        existing = MeetingRating.objects.filter(meeting=meeting, participant=request.user).first()
        form = MeetingRatingForm(request.POST, instance=existing)
        if form.is_valid():
            rating = form.save(commit=False)
            rating.meeting = meeting
            rating.participant = request.user
            rating.save()
            messages.success(request, f'Rating saved: {rating.score}/10')
        return redirect('meetings:detail', pk=pk)


# ---------------------------------------------------------------------------
# Meeting notes
# ---------------------------------------------------------------------------

class MeetingNoteSaveView(LoginRequiredMixin, View):
    """POST: create or update the notes block for the current segment."""

    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        meeting = get_object_or_404(Meeting, pk=pk, team__organization=org)
        if not meeting.is_active:
            return redirect('meetings:detail', pk=pk)
        text = request.POST.get('notes', '').strip()
        if text:
            MeetingNote.objects.update_or_create(
                meeting=meeting,
                segment=meeting.current_segment,
                defaults={'text': text, 'updated_by': request.user},
            )
        else:
            MeetingNote.objects.filter(meeting=meeting, segment=meeting.current_segment).delete()
        return redirect('meetings:detail', pk=pk)
