from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, UpdateView, DeleteView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.contrib import messages

from .models import AccountabilityNode, AccountabilityRole
from .forms import NodeForm, RoleForm
from apps.accounts.scoping import get_active_org


def _get_org(request):
    return get_active_org(request)


def _build_tree(org):
    """Return a list of root nodes with child_nodes lists attached recursively."""
    nodes = list(
        AccountabilityNode.objects
        .filter(organization=org)
        .select_related('owner', 'parent')
        .prefetch_related('roles')
        .order_by('order', 'name')
    )
    node_map = {n.pk: n for n in nodes}
    for n in nodes:
        n.child_nodes = []
    roots = []
    for n in nodes:
        if n.parent_id and n.parent_id in node_map:
            node_map[n.parent_id].child_nodes.append(n)
        else:
            roots.append(n)
    return roots


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------

class ChartView(LoginRequiredMixin, View):
    template_name = 'accountability/chart.html'

    def get(self, request):
        org = _get_org(request)
        if not org:
            messages.warning(request, 'Set up your organisation first.')
            return redirect('accounts:org_setup')
        roots = _build_tree(org)
        has_nodes = AccountabilityNode.objects.filter(organization=org).exists()
        return render(request, self.template_name, {
            'org': org,
            'roots': roots,
            'has_nodes': has_nodes,
        })


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

class NodeCreateView(LoginRequiredMixin, View):
    template_name = 'accountability/node_form.html'

    def _setup(self, request):
        org = _get_org(request)
        return org

    def _get_parent(self, request, org, source):
        pk = source.get('parent_pk') or source.get('parent')
        if pk:
            return AccountabilityNode.objects.filter(pk=pk, organization=org).first()
        return None

    def get(self, request):
        org = self._setup(request)
        if not org:
            return redirect('accounts:org_setup')
        parent = self._get_parent(request, org, request.GET)
        form = NodeForm(org=org)
        return render(request, self.template_name, {
            'form': form, 'action': 'Add', 'parent': parent,
        })

    def post(self, request):
        org = self._setup(request)
        if not org:
            return redirect('accounts:org_setup')
        parent = self._get_parent(request, org, request.POST)
        form = NodeForm(request.POST, org=org)
        if form.is_valid():
            node = form.save(commit=False)
            node.organization = org
            node.parent = parent
            node.save()
            messages.success(request, f'"{node.name}" added to the chart.')
            return redirect('accountability:chart')
        return render(request, self.template_name, {
            'form': form, 'action': 'Add', 'parent': parent,
        })


class NodeUpdateView(LoginRequiredMixin, View):
    template_name = 'accountability/node_form.html'

    def _get_node(self, request, pk):
        org = _get_org(request)
        if not org:
            return None, None
        return get_object_or_404(AccountabilityNode, pk=pk, organization=org), org

    def get(self, request, pk):
        node, org = self._get_node(request, pk)
        if not org:
            return redirect('accounts:org_setup')
        form = NodeForm(instance=node, org=org)
        return render(request, self.template_name, {
            'form': form, 'action': 'Edit', 'node': node,
        })

    def post(self, request, pk):
        node, org = self._get_node(request, pk)
        if not org:
            return redirect('accounts:org_setup')
        form = NodeForm(request.POST, instance=node, org=org)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{node.name}" updated.')
            return redirect('accountability:chart')
        return render(request, self.template_name, {
            'form': form, 'action': 'Edit', 'node': node,
        })


class NodeDeleteView(LoginRequiredMixin, DeleteView):
    model = AccountabilityNode
    template_name = 'accountability/node_confirm_delete.html'
    success_url = reverse_lazy('accountability:chart')

    def get_queryset(self):
        org = _get_org(self.request)
        return AccountabilityNode.objects.filter(organization=org)

    def form_valid(self, form):
        messages.success(self.request, f'"{self.object.name}" removed from the chart.')
        return super().form_valid(form)


class NodeMoveView(LoginRequiredMixin, View):
    """Reorder a node among its siblings."""

    def post(self, request, pk):
        org = _get_org(request)
        if not org:
            return redirect('accounts:org_setup')
        node = get_object_or_404(AccountabilityNode, pk=pk, organization=org)
        direction = request.POST.get('direction')
        siblings = list(
            AccountabilityNode.objects
            .filter(organization=org, parent=node.parent)
            .order_by('order', 'pk')
        )
        idx = next((i for i, s in enumerate(siblings) if s.pk == node.pk), None)
        if idx is not None:
            if direction == 'up' and idx > 0:
                siblings.insert(idx - 1, siblings.pop(idx))
            elif direction == 'down' and idx < len(siblings) - 1:
                siblings.insert(idx + 1, siblings.pop(idx))
            for i, sib in enumerate(siblings):
                if sib.order != i:
                    sib.order = i
                    sib.save(update_fields=['order'])
        return redirect('accountability:chart')


# ---------------------------------------------------------------------------
# Role CRUD
# ---------------------------------------------------------------------------

class RoleCreateView(LoginRequiredMixin, View):
    template_name = 'accountability/role_form.html'

    def _get_node(self, request, pk):
        org = _get_org(request)
        if not org:
            return None
        return get_object_or_404(AccountabilityNode, pk=pk, organization=org)

    def get(self, request, pk):
        node = self._get_node(request, pk)
        if not node:
            return redirect('accounts:org_setup')
        return render(request, self.template_name, {
            'form': RoleForm(), 'node': node, 'action': 'Add',
        })

    def post(self, request, pk):
        node = self._get_node(request, pk)
        if not node:
            return redirect('accounts:org_setup')
        form = RoleForm(request.POST)
        if form.is_valid():
            role = form.save(commit=False)
            role.node = node
            role.save()
            messages.success(request, 'Accountability added.')
            return redirect('accountability:chart')
        return render(request, self.template_name, {
            'form': form, 'node': node, 'action': 'Add',
        })


class RoleUpdateView(LoginRequiredMixin, UpdateView):
    model = AccountabilityRole
    form_class = RoleForm
    template_name = 'accountability/role_form.html'
    success_url = reverse_lazy('accountability:chart')

    def get_queryset(self):
        org = _get_org(self.request)
        return AccountabilityRole.objects.filter(node__organization=org)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['action'] = 'Edit'
        ctx['node'] = self.object.node
        return ctx

    def form_valid(self, form):
        messages.success(self.request, 'Accountability updated.')
        return super().form_valid(form)


class RoleDeleteView(LoginRequiredMixin, DeleteView):
    model = AccountabilityRole
    template_name = 'accountability/role_confirm_delete.html'
    success_url = reverse_lazy('accountability:chart')

    def get_queryset(self):
        org = _get_org(self.request)
        return AccountabilityRole.objects.filter(node__organization=org)

    def form_valid(self, form):
        messages.success(self.request, 'Accountability removed.')
        return super().form_valid(form)
