from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .forms import BankQuestionForm, BankSearchForm
from .models import BankQuestion, Exam
from .permissions import teacher_only
from .services import add_bank_question, save_question_to_bank


@teacher_only
@require_safe
def question_bank(request):
    exam = None
    if request.GET.get("exam"):
        try:
            exam_id = int(request.GET["exam"])
        except ValueError as error:
            raise Http404 from error
        if not 0 < exam_id <= 2**63 - 1:
            raise Http404
        exam = get_object_or_404(Exam, pk=exam_id, course__teacher=request.user)
        if exam.published or exam.attempts.exists():
            raise PermissionDenied("Questions can only be added to an unused draft exam.")

    form = BankSearchForm(request.GET)
    questions = BankQuestion.objects.filter(teacher=request.user)
    filters = {"exam": exam.pk} if exam else {}
    if form.is_valid():
        query, kind = form.cleaned_data["q"], form.cleaned_data["kind"]
        if query:
            questions = questions.filter(
                Q(title__icontains=query) | Q(topic__icontains=query) | Q(prompt__icontains=query)
            )
            filters["q"] = query
        if kind:
            questions = questions.filter(kind=kind)
            filters["kind"] = kind
    else:
        questions = questions.none()
    return render(
        request,
        "classroom/question_bank.html",
        {
            "form": form,
            "questions": Paginator(questions, 12).get_page(request.GET.get("page")),
            "exam": exam,
            "exam_full": exam.questions.count() >= 50 if exam else False,
            "filter_query": urlencode(filters),
            "clear_url": reverse("question_bank") + (f"?exam={exam.pk}" if exam else ""),
        },
    )


@teacher_only
@require_http_methods(["GET", "POST"])
def bank_question_edit(request, pk=None):
    question = (
        get_object_or_404(BankQuestion, pk=pk, teacher=request.user)
        if pk is not None
        else BankQuestion(teacher=request.user)
    )
    form = BankQuestionForm(request.POST if request.method == "POST" else None, instance=question)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Question saved to your bank. Existing exam copies are unchanged.")
        return redirect("question_bank")
    return render(
        request,
        "classroom/form.html",
        {
            "form": form,
            "title": "Edit bank question" if pk is not None else "Create a bank question",
            "eyebrow": "YOUR QUESTION BANK",
            "button": "Save to bank",
            "back_url": reverse("question_bank"),
            "question_form": True,
        },
    )


@teacher_only
@require_POST
def bank_question_delete(request, pk):
    get_object_or_404(BankQuestion, pk=pk, teacher=request.user).delete()
    messages.success(request, "Bank question removed. Existing exam copies are unchanged.")
    return redirect("question_bank")


@teacher_only
@require_POST
def question_to_bank(request, exam_id, pk):
    question = save_question_to_bank(exam_id, pk, request.user)
    messages.success(request, "Question copied to your bank. You can give it a title and topic below.")
    return redirect("bank_question_edit", pk=question.pk)


@teacher_only
@require_POST
def bank_question_add(request, exam_id, pk):
    try:
        add_bank_question(exam_id, pk, request.user)
        messages.success(request, "Question copied into this draft. You can edit it independently.")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("exam_edit", pk=exam_id)
