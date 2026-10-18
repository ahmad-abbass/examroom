from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Course, Exam, Question


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label="Your name")
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ["first_name", "username", "email", "password1", "password2"]


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ["name", "code", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class ExamForm(forms.ModelForm):
    class Meta:
        model = Exam
        fields = ["title", "instructions", "duration_minutes", "opens_at", "closes_at"]
        widgets = {
            "instructions": forms.Textarea(attrs={"rows": 3}),
            "opens_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "closes_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }
        help_texts = {
            "opens_at": "Optional. Local time: Asia/Jerusalem.",
            "closes_at": "Optional. The closing time also ends active attempts.",
        }

    def clean(self):
        data = super().clean()
        start, end = data.get("opens_at"), data.get("closes_at")
        if start and end and start >= end:
            raise forms.ValidationError("The closing time must be after the opening time.")
        return data


class QuestionForm(forms.ModelForm):
    option_a = forms.CharField(max_length=500, required=False)
    option_b = forms.CharField(max_length=500, required=False)
    option_c = forms.CharField(max_length=500, required=False)
    option_d = forms.CharField(max_length=500, required=False)
    correct_option = forms.TypedChoiceField(
        choices=[(i, letter) for i, letter in enumerate("ABCD")], coerce=int, required=False
    )

    class Meta:
        model = Question
        fields = ["kind", "prompt", "points", "explanation", "correct_option"]
        widgets = {
            "prompt": forms.Textarea(attrs={"rows": 3}),
            "explanation": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {"explanation": "Shown to students only after results are released."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key, value in zip("abcd", self.instance.options or []):
            self.fields[f"option_{key}"].initial = value

    def clean(self):
        data = super().clean()
        if data.get("kind") == Question.Kind.CHOICE:
            if any(not data.get(f"option_{key}", "").strip() for key in "abcd"):
                raise forms.ValidationError("Multiple-choice questions require four non-empty options.")
            if data.get("correct_option") not in range(4):
                raise forms.ValidationError("Choose a correct answer.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.options = (
            [self.cleaned_data[f"option_{key}"].strip() for key in "abcd"]
            if obj.kind == Question.Kind.CHOICE
            else []
        )
        obj.correct_option = self.cleaned_data["correct_option"] if obj.kind == Question.Kind.CHOICE else None
        if commit:
            obj.save()
        return obj
