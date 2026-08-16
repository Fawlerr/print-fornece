from django import forms
from django.utils import timezone

from .models import BugReport


class BugReportCreateForm(forms.ModelForm):
    current_url = forms.CharField(
        label="Tela / Rota onde ocorreu",
        required=False,
        widget=forms.TextInput(attrs={"readonly": "readonly", "class": "readonly-input"}),
    )
    screenshot = forms.ImageField(
        label="Print / Captura de tela",
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/*"}),
    )

    class Meta:
        model = BugReport
        fields = ["description", "screenshot", "current_url"]
        labels = {
            "description": "Relato detalhado do problema",
        }
        widgets = {
            "description": forms.Textarea(attrs={
                "rows": 4,
                "placeholder": "Descreva o que você estava fazendo, o que esperava que acontecesse e o que deu errado…",
                "required": "required",
            }),
        }


class BugReportDevUpdateForm(forms.ModelForm):
    class Meta:
        model = BugReport
        fields = ["status", "dev_notes"]
        labels = {
            "status": "Situação do Report",
            "dev_notes": "Anotações técnicas / Resolução",
        }
        widgets = {
            "dev_notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Detalhes da análise, commit ou solução aplicada…"}),
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.status == BugReport.Status.FIXED and not instance.resolved_at:
            instance.resolved_at = timezone.now()
        elif instance.status != BugReport.Status.FIXED:
            instance.resolved_at = None
        if commit:
            instance.save()
        return instance
