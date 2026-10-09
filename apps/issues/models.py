from django.db import models
from django.contrib.auth.models import User
from django.urls import reverse

from apps.accounts.models import Team


class Issue(models.Model):
    TYPE_SHORT_TERM = 'short_term'
    TYPE_LONG_TERM = 'long_term'
    TYPE_CHOICES = [
        (TYPE_SHORT_TERM, 'Short-term'),
        (TYPE_LONG_TERM, 'Long-term'),
    ]

    STATUS_OPEN = 'open'
    STATUS_IN_IDS = 'in_ids'
    STATUS_RESOLVED = 'resolved'
    STATUS_DROPPED = 'dropped'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_IN_IDS, 'In IDS'),
        (STATUS_RESOLVED, 'Resolved'),
        (STATUS_DROPPED, 'Dropped'),
    ]

    QUARTER_CHOICES = [(i, f'Q{i}') for i in range(1, 5)]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    originating_team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name='originated_issues'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='created_issues'
    )
    issue_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default=TYPE_SHORT_TERM
    )
    is_company_issue = models.BooleanField(
        default=False,
        help_text='Company-wide long-term Issues appear on the VTO. Other Issues stay on their team\'s own list.',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN
    )
    delegated_to_team = models.ForeignKey(
        Team, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='delegated_issues'
    )
    linked_rocks = models.ManyToManyField(
        'rocks.Rock', blank=True, related_name='linked_issues'
    )
    # For long-term issues: which quarter to address
    target_quarter = models.PositiveSmallIntegerField(
        choices=QUARTER_CHOICES, null=True, blank=True
    )
    target_year = models.PositiveSmallIntegerField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('issues:detail', kwargs={'pk': self.pk})

    # ── State helpers ────────────────────────────────────────────────────────

    @property
    def is_open(self):
        return self.status in (self.STATUS_OPEN, self.STATUS_IN_IDS)

    @property
    def is_resolved(self):
        return self.status == self.STATUS_RESOLVED

    @property
    def is_delegated(self):
        return self.delegated_to_team_id is not None

    @property
    def active_team(self):
        """The team currently responsible for resolving this issue."""
        return self.delegated_to_team or self.originating_team

    @property
    def status_badge_class(self):
        return {
            self.STATUS_OPEN: 'primary',
            self.STATUS_IN_IDS: 'warning text-dark',
            self.STATUS_RESOLVED: 'success',
            self.STATUS_DROPPED: 'secondary',
        }.get(self.status, 'secondary')

    @property
    def type_badge_class(self):
        return 'purple' if self.issue_type == self.TYPE_LONG_TERM else 'info text-dark'


class IssueActivity(models.Model):
    ACTION_CREATED = 'created'
    ACTION_DELEGATED = 'delegated'
    ACTION_RECALLED = 'recalled'
    ACTION_STATUS_CHANGED = 'status_changed'
    ACTION_ROCK_LINKED = 'rock_linked'
    ACTION_ROCK_UNLINKED = 'rock_unlinked'
    ACTION_COMMENT = 'comment'
    ACTION_RESOLVED = 'resolved'
    ACTION_DROPPED = 'dropped'

    ACTION_CHOICES = [
        (ACTION_CREATED, 'Created'),
        (ACTION_DELEGATED, 'Delegated'),
        (ACTION_RECALLED, 'Recalled'),
        (ACTION_STATUS_CHANGED, 'Status Changed'),
        (ACTION_ROCK_LINKED, 'Rock Linked'),
        (ACTION_ROCK_UNLINKED, 'Rock Unlinked'),
        (ACTION_COMMENT, 'Comment'),
        (ACTION_RESOLVED, 'Resolved'),
        (ACTION_DROPPED, 'Dropped'),
    ]

    issue = models.ForeignKey(
        Issue, on_delete=models.CASCADE, related_name='activity'
    )
    actor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='issue_activities'
    )
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'{self.get_action_display()} on "{self.issue}" by {self.actor}'

    @property
    def icon(self):
        return {
            self.ACTION_CREATED: 'bi-plus-circle text-success',
            self.ACTION_DELEGATED: 'bi-arrow-right-circle text-primary',
            self.ACTION_RECALLED: 'bi-arrow-left-circle text-secondary',
            self.ACTION_STATUS_CHANGED: 'bi-arrow-repeat text-info',
            self.ACTION_ROCK_LINKED: 'bi-gem text-success',
            self.ACTION_ROCK_UNLINKED: 'bi-gem text-secondary',
            self.ACTION_COMMENT: 'bi-chat-left-text text-muted',
            self.ACTION_RESOLVED: 'bi-check-circle text-success',
            self.ACTION_DROPPED: 'bi-x-circle text-secondary',
        }.get(self.action, 'bi-circle text-muted')
