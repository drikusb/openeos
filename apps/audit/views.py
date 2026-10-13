from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.utils.http import urlencode
from django.views.generic import ListView

from apps.accounts.scoping import get_active_org, is_org_admin

from .models import AuditEvent


class AuditEventListView(LoginRequiredMixin, ListView):
    """The active organisation's audit log, for its admins and superusers.

    Superusers see the same organisation-scoped list here; the Django admin is
    the place to look across every organisation.
    """

    model = AuditEvent
    template_name = 'audit/event_list.html'
    context_object_name = 'events'
    paginate_by = 50

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.org = get_active_org(request)
        if self.org is None:
            return redirect('accounts:org_setup')
        if not is_org_admin(request.user, self.org):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = (
            AuditEvent.objects
            .filter(organization=self.org)
            .select_related('actor')
        )
        action = self.request.GET.get('action', '').strip()
        if action:
            queryset = queryset.filter(action=action)
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        selected = self.request.GET.get('action', '').strip()
        ctx['org'] = self.org
        ctx['selected_action'] = selected
        # Appended to page links so the action filter survives paging.
        ctx['page_suffix'] = f'&{urlencode({"action": selected})}' if selected else ''
        ctx['actions'] = (
            AuditEvent.objects
            .filter(organization=self.org)
            .order_by('action')
            .values_list('action', flat=True)
            .distinct()
        )
        return ctx
