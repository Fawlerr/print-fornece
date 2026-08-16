from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import BugReportCreateForm, BugReportDevUpdateForm
from .models import BugReport


class BugReportCreateAjaxView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        form = BugReportCreateForm(request.POST, request.FILES)
        if form.is_valid():
            report = form.save(commit=False)
            report.user = request.user
            if not report.current_url:
                report.current_url = request.META.get("HTTP_REFERER", "/")
            report.save()

            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.content_type == "multipart/form-data":
                return JsonResponse({
                    "success": True,
                    "id": report.pk,
                    "message": "Relato de bug enviado com sucesso! O desenvolvedor irá analisar.",
                })
            messages.success(request, "Relato de bug enviado com sucesso! O desenvolvedor irá analisar.")
            return redirect(request.POST.get("return_url") or "bug_reports:list")

        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"success": False, "errors": form.errors}, status=400)

        messages.error(request, "Não foi possível enviar o relato. Verifique os campos.")
        return redirect(request.META.get("HTTP_REFERER", "bug_reports:list"))


class BugReportListView(LoginRequiredMixin, ListView):
    model = BugReport
    template_name = "bug_reports/list.html"
    context_object_name = "reports"
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        qs = BugReport.objects.select_related("user").all()
        if not getattr(user, "is_dev", False):
            qs = qs.filter(user=user)

        status_filter = self.request.GET.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        base_qs = BugReport.objects.all() if getattr(user, "is_dev", False) else BugReport.objects.filter(user=user)

        context["total_count"] = base_qs.count()
        context["pending_count"] = base_qs.filter(status=BugReport.Status.PENDING).count()
        context["verified_count"] = base_qs.filter(status=BugReport.Status.VERIFIED).count()
        context["fixed_count"] = base_qs.filter(status=BugReport.Status.FIXED).count()
        context["current_status"] = self.request.GET.get("status", "")
        context["is_dev_user"] = getattr(user, "is_dev", False)
        return context


class BugReportDetailView(LoginRequiredMixin, DetailView):
    model = BugReport
    template_name = "bug_reports/detail.html"
    context_object_name = "report"

    def get_object(self, queryset=None):
        report = super().get_object(queryset)
        user = self.request.user
        if not getattr(user, "is_dev", False) and report.user != user:
            raise PermissionDenied("Você não tem permissão para visualizar este relato.")
        return report

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if getattr(self.request.user, "is_dev", False):
            context["dev_form"] = BugReportDevUpdateForm(instance=self.object)
        return context


class BugReportUpdateView(LoginRequiredMixin, UpdateView):
    model = BugReport
    template_name = "bug_reports/form.html"
    form_class = BugReportCreateForm
    success_url = reverse_lazy("bug_reports:list")

    def get_object(self, queryset=None):
        report = super().get_object(queryset)
        user = self.request.user
        if not getattr(user, "is_dev", False) and report.user != user:
            raise PermissionDenied("Você não tem permissão para editar este relato.")
        if not getattr(user, "is_dev", False) and report.status != BugReport.Status.PENDING:
            raise PermissionDenied("Relatos já analisados ou corrigidos não podem ser editados.")
        return report

    def form_valid(self, form):
        messages.success(self.request, "Relato atualizado com sucesso.")
        return super().form_valid(form)


class BugReportDevStatusView(LoginRequiredMixin, UserPassesTestMixin, View):
    def test_func(self):
        return getattr(self.request.user, "is_dev", False)

    def post(self, request, pk, *args, **kwargs):
        report = get_object_or_404(BugReport, pk=pk)
        new_status = request.POST.get("status")
        dev_notes = request.POST.get("dev_notes", "")

        if new_status in BugReport.Status.values:
            report.status = new_status
            if dev_notes:
                report.dev_notes = dev_notes
            if new_status == BugReport.Status.FIXED:
                report.resolved_at = timezone.now()
            else:
                report.resolved_at = None
            report.save()
            messages.success(request, f"Status do Bug #{report.pk} alterado para '{report.get_status_display()}'.")
        else:
            messages.error(request, "Status inválido.")

        return redirect(request.POST.get("return_url") or "bug_reports:detail", pk=report.pk)
