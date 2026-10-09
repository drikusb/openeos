from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, CreateView, UpdateView, DeleteView, TemplateView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.contrib import messages

from .models import VTO, VTOCoreValue, VTOSection, VTOSectionHistory, SectionKey
from .forms import VTOSectionForm, VTOCoreValueForm
from apps.accounts.scoping import OrgScopedMixin, get_active_org
from apps.rocks.models import Rock


def _get_vto(request):
    org = get_active_org(request)
    if not org:
        return None
    return VTO.for_org(org)


def _current_rocks(org):
    from apps.rocks.models import Rock
    q, y = Rock.current_quarter(), Rock.current_year()
    return (
        Rock.objects
        .filter(team__organization=org, quarter=q, year=y, is_company_rock=True,
                status__in=[Rock.STATUS_ON_TRACK, Rock.STATUS_OFF_TRACK])
        .select_related('owner', 'team')
        .order_by('team__name', 'title')
    )


def _long_term_issues(org):
    from apps.issues.models import Issue
    return (
        Issue.objects
        .filter(originating_team__organization=org,
                issue_type=Issue.TYPE_LONG_TERM,
                status__in=[Issue.STATUS_OPEN, Issue.STATUS_IN_IDS])
        .select_related('originating_team')
        .order_by('target_year', 'target_quarter', 'title')
    )


def _build_context(vto, org):
    """Build the full VTO context dict shared by detail and print views."""
    sections = {s.key: s for s in vto.sections.select_related('last_edited_by')}
    return {
        'vto': vto,
        'core_values': vto.core_values.all(),
        'sections': sections,
        'section_keys': SectionKey,
        'rocks': _current_rocks(org),
        'long_term_issues': _long_term_issues(org),
        'rock_quarter': f'Q{Rock.current_quarter()} {Rock.current_year()}',
    }


# ---------------------------------------------------------------------------
# VTO detail
# ---------------------------------------------------------------------------

class VTODetailView(LoginRequiredMixin, View):
    template_name = 'vto/vto_detail.html'

    def get(self, request):
        org = get_active_org(request)
        if not org:
            messages.warning(request, 'Set up your organisation first.')
            return redirect('accounts:org_setup')
        vto = VTO.for_org(org)
        ctx = _build_context(vto, org)
        return render(request, self.template_name, ctx)


class VTOPrintView(LoginRequiredMixin, View):
    template_name = 'vto/vto_print.html'

    def get(self, request):
        org = get_active_org(request)
        if not org:
            return redirect('accounts:org_setup')
        vto = VTO.for_org(org)
        ctx = _build_context(vto, org)
        return render(request, self.template_name, ctx)


# ---------------------------------------------------------------------------
# Section editing
# ---------------------------------------------------------------------------

class VTOSectionEditView(LoginRequiredMixin, View):
    template_name = 'vto/section_edit.html'

    def _get_or_create_section(self, vto, key):
        section, _ = VTOSection.objects.get_or_create(vto=vto, key=key)
        return section

    def get(self, request, key):
        if key not in SectionKey.ALL:
            messages.error(request, 'Unknown section.')
            return redirect('vto:detail')
        vto = _get_vto(request)
        if not vto:
            return redirect('accounts:org_setup')
        section = self._get_or_create_section(vto, key)
        form = VTOSectionForm(initial={'content': section.content}, key=key)
        history = section.history.select_related('edited_by')[:5]
        return render(request, self.template_name, {
            'vto': vto, 'section': section, 'form': form,
            'key': key, 'label': SectionKey.LABELS.get(key, key),
            'history': history,
        })

    def post(self, request, key):
        if key not in SectionKey.ALL:
            return redirect('vto:detail')
        vto = _get_vto(request)
        if not vto:
            return redirect('accounts:org_setup')
        section = self._get_or_create_section(vto, key)
        form = VTOSectionForm(request.POST, key=key)
        if form.is_valid():
            section.save_content(form.cleaned_data['content'], request.user)
            messages.success(request, f'"{SectionKey.LABELS.get(key)}" updated.')
            return redirect('vto:detail')
        history = section.history.select_related('edited_by')[:5]
        return render(request, self.template_name, {
            'vto': vto, 'section': section, 'form': form,
            'key': key, 'label': SectionKey.LABELS.get(key, key),
            'history': history,
        })


# ---------------------------------------------------------------------------
# Core Values CRUD
# ---------------------------------------------------------------------------

class CoreValueCreateView(LoginRequiredMixin, View):
    template_name = 'vto/core_value_form.html'

    def get(self, request):
        return render(request, self.template_name, {
            'form': VTOCoreValueForm(),
            'action': 'Add',
        })

    def post(self, request):
        vto = _get_vto(request)
        if not vto:
            return redirect('accounts:org_setup')
        form = VTOCoreValueForm(request.POST)
        if form.is_valid():
            cv = form.save(commit=False)
            cv.vto = vto
            cv.save()
            messages.success(request, f'Core Value "{cv.name}" added.')
            return redirect('vto:detail')
        return render(request, self.template_name, {'form': form, 'action': 'Add'})


class CoreValueUpdateView(LoginRequiredMixin, OrgScopedMixin, UpdateView):
    model = VTOCoreValue
    org_lookup = 'vto__organization'
    form_class = VTOCoreValueForm
    template_name = 'vto/core_value_form.html'
    success_url = reverse_lazy('vto:detail')

    def form_valid(self, form):
        messages.success(self.request, f'Core Value "{form.instance.name}" updated.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        return ctx


class CoreValueDeleteView(LoginRequiredMixin, OrgScopedMixin, DeleteView):
    model = VTOCoreValue
    org_lookup = 'vto__organization'
    template_name = 'vto/core_value_confirm_delete.html'
    success_url = reverse_lazy('vto:detail')

    def form_valid(self, form):
        messages.success(self.request, f'Core Value "{self.object.name}" removed.')
        return super().form_valid(form)
