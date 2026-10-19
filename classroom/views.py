import csv
import hashlib
import json
from datetime import timedelta
from functools import wraps
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CourseForm, ExamForm, QuestionForm, RegisterForm
from .gradebooks import STATUSES, filter_rows, gradebook_rows
from .models import Attempt, Course, Enrollment, Exam, LoginThrottle, Profile, Question
from .services import (
    RevisionConflict,
    available,
    duplicate_exam,
    finalize_expired,
    move_question,
    publish_exam,
    save_answers,
    start_attempt,
    update_invitation,
)


def role_required(role):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.user.profile.role != role:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


teacher_only = role_required(Profile.Role.TEACHER)
student_only = role_required(Profile.Role.STUDENT)


class SignIn(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def throttle_key(self):
        identity = self.request.POST.get("username", "").casefold()[:150]
        address = self.request.META.get("REMOTE_ADDR", "")
        return hashlib.sha256(f"{address}:{identity}".encode()).hexdigest()

    def post(self, request, *args, **kwargs):
        cutoff = timezone.now() - timedelta(minutes=5)
        if LoginThrottle.objects.filter(key=self.throttle_key(), failures__gte=8, since__gt=cutoff).exists():
            form = self.get_form()
            form.is_valid()
            form.add_error(None, "Too many sign-in attempts. Please try again in five minutes.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        with transaction.atomic():
            throttle, _ = LoginThrottle.objects.select_for_update().get_or_create(
                key=self.throttle_key(), defaults={"since": timezone.now()}
            )
            if throttle.since <= timezone.now() - timedelta(minutes=5):
                throttle.failures, throttle.since = 0, timezone.now()
            throttle.failures += 1
            throttle.save()
        return super().form_invalid(form)

    def form_valid(self, form):
        LoginThrottle.objects.filter(key=self.throttle_key()).delete()
        return super().form_valid(form)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()  # Profile defaults to student. A posted role cannot grant teacher access.
        login(request, user)
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


@login_required
def dashboard(request):
    teacher = request.user.profile.role == Profile.Role.TEACHER
    if teacher:
        courses = Course.objects.filter(teacher=request.user).annotate(
            student_count=Count("enrollments", distinct=True)
        )
        exams = (
            Exam.objects.filter(course__teacher=request.user)
            .select_related("course")
            .prefetch_related("questions")
            .annotate(submission_count=Count("attempts", distinct=True))
        )
        pending = (
            Attempt.objects.filter(
                exam__course__teacher=request.user,
                submitted_at__isnull=False,
                answers__awarded_points__isnull=True,
            )
            .distinct()
            .count()
        )
        stats = [
            ("Classes", courses.count()),
            ("Published exams", exams.filter(published=True).count()),
            ("To review", pending),
        ]
        return render(
            request, "classroom/dashboard.html", {"courses": courses, "exams": exams[:6], "stats": stats}
        )
    courses = Course.objects.filter(enrollments__student=request.user).select_related("teacher")
    exams = (
        Exam.objects.filter(course__in=courses, published=True)
        .select_related("course")
        .prefetch_related("questions")
    )
    attempts = {
        a.exam_id: a for a in request.user.attempts.select_related("exam").prefetch_related("answers")
    }
    cards = []
    for exam in exams:
        attempt = attempts.get(exam.pk)
        status = (
            "Available"
            if available(exam)
            else ("Upcoming" if exam.opens_at and timezone.now() < exam.opens_at else "Closed")
        )
        if attempt:
            attempt = finalize_expired(attempt.pk)
            status = (
                "Results ready"
                if attempt.submitted_at and exam.results_released and attempt.graded
                else ("Submitted" if attempt.submitted_at else "In progress")
            )
        cards.append({"exam": exam, "attempt": attempt, "status": status})
    stats = [
        ("Classes", courses.count()),
        ("Assigned exams", len(cards)),
        ("Completed", sum(bool(c["attempt"] and c["attempt"].submitted_at) for c in cards)),
    ]
    return render(request, "classroom/dashboard.html", {"courses": courses, "cards": cards, "stats": stats})


@teacher_only
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        course = form.save(commit=False)
        course.teacher = request.user
        course.save()
        messages.success(request, "Class created. Share its join code with your students.")
        return redirect("course", pk=course.pk)
    return render(
        request,
        "classroom/form.html",
        {"form": form, "title": "Create a class", "eyebrow": "Your teaching space", "button": "Create class"},
    )


@login_required
def course_detail(request, pk):
    course = get_object_or_404(Course.objects.select_related("teacher"), pk=pk)
    teacher = course.teacher_id == request.user.pk
    if not teacher and not course.enrollments.filter(student=request.user).exists():
        raise PermissionDenied
    exams = course.exams.prefetch_related("questions")
    if not teacher:
        exams = exams.filter(published=True)
    return render(
        request,
        "classroom/course.html",
        {
            "course": course,
            "exams": exams,
            "roster": course.enrollments.select_related("student") if teacher else None,
        },
    )


@student_only
@require_POST
def join_course(request):
    code = request.POST.get("code", "").strip().upper()
    with transaction.atomic():
        course = Course.objects.select_for_update().filter(join_code=code).first()
        if not course:
            messages.error(request, "That join code was not found. Ask your teacher to check it.")
        elif not course.join_enabled:
            messages.error(request, "New joins are paused for this class. Contact your teacher.")
        else:
            Enrollment.objects.get_or_create(course=course, student=request.user)
            messages.success(request, f"You joined {course.name}.")
    return redirect("dashboard")


@teacher_only
@require_POST
def course_invitation(request, pk):
    get_object_or_404(Course, pk=pk, teacher=request.user)
    action = request.POST.get("action")
    try:
        update_invitation(pk, request.user, action)
        text = {
            "rotate": "Join code replaced. The previous code no longer works.",
            "open": "New students can join this class.",
            "close": "New joins paused. Enrolled students keep their access.",
        }[action]
        messages.success(request, text)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("course", pk=pk)


@teacher_only
def exam_create(request, course_id):
    course = get_object_or_404(Course, pk=course_id, teacher=request.user)
    form = ExamForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        exam = form.save(commit=False)
        exam.course = course
        exam.save()
        return redirect("exam_edit", pk=exam.pk)
    return render(
        request,
        "classroom/form.html",
        {"form": form, "title": "Create an exam", "eyebrow": course.name, "button": "Continue to questions"},
    )


@teacher_only
@require_POST
def exam_duplicate(request, pk):
    get_object_or_404(Exam, pk=pk, course__teacher=request.user)
    draft = duplicate_exam(pk, request.user)
    messages.success(request, "Exam copied to a fresh draft. Set its schedule before publishing.")
    return redirect("exam_edit", pk=draft.pk)


@teacher_only
def exam_edit(request, pk):
    exam = get_object_or_404(Exam, pk=pk, course__teacher=request.user)
    form = ExamForm(request.POST or None, instance=exam)
    if request.method == "POST":
        with transaction.atomic():
            exam = Exam.objects.select_for_update().get(pk=exam.pk)
            if exam.published:
                raise PermissionDenied("Published exams are frozen to protect existing attempts.")
            if form.is_valid():
                form.save()
                messages.success(request, "Exam details saved.")
                return redirect("exam_edit", pk=exam.pk)
    return render(request, "classroom/exam_edit.html", {"exam": exam, "form": form})


@teacher_only
def question_edit(request, exam_id, pk=None):
    exam = get_object_or_404(Exam, pk=exam_id, course__teacher=request.user)
    question = (
        get_object_or_404(Question, pk=pk, exam=exam)
        if pk
        else Question(exam=exam, position=exam.questions.count())
    )
    if exam.published:
        raise PermissionDenied("Published exams cannot be edited.")
    form = QuestionForm(request.POST or None, instance=question)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked = Exam.objects.select_for_update().get(pk=exam.pk)
            if locked.published:
                raise PermissionDenied
            if pk is None and locked.questions.count() >= 50:
                form.add_error(None, "An exam can contain at most 50 questions.")
            else:
                if pk is None:
                    form.instance.position = locked.questions.count()
                form.save()
                messages.success(request, "Question saved.")
                return redirect("exam_edit", pk=exam.pk)
    return render(
        request,
        "classroom/form.html",
        {
            "form": form,
            "title": "Edit question" if pk else "Add a question",
            "eyebrow": exam.title,
            "button": "Save question",
            "back_url": reverse("exam_edit", args=[exam.pk]),
            "question_form": True,
        },
    )


@teacher_only
@require_POST
def question_move(request, exam_id, pk):
    get_object_or_404(Question, pk=pk, exam_id=exam_id, exam__course__teacher=request.user)
    try:
        if move_question(exam_id, pk, request.user, request.POST.get("direction")):
            messages.success(request, "Question order updated.")
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("exam_edit", pk=exam_id)


@teacher_only
@require_POST
def question_delete(request, exam_id, pk):
    with transaction.atomic():
        exam = get_object_or_404(Exam.objects.select_for_update(), pk=exam_id, course__teacher=request.user)
        if exam.published:
            raise PermissionDenied
        get_object_or_404(Question, pk=pk, exam=exam).delete()
        for position, question in enumerate(exam.questions.all()):
            if question.position != position:
                question.position = position
                question.save(update_fields=["position"])
    messages.success(request, "Question removed.")
    return redirect("exam_edit", pk=exam.pk)


@teacher_only
@require_POST
def exam_publish(request, pk):
    get_object_or_404(Exam, pk=pk, course__teacher=request.user)
    try:
        publish_exam(pk, request.user)
        messages.success(
            request, "Exam published. Enrolled students can access it during its availability window."
        )
    except ValidationError as error:
        messages.error(request, error.messages[0])
    return redirect("exam_edit", pk=pk)


@student_only
def exam_intro(request, pk):
    exam = get_object_or_404(Exam, pk=pk, published=True, course__enrollments__student=request.user)
    attempt = Attempt.objects.filter(exam=exam, student=request.user).first()
    if attempt:
        return redirect("attempt", pk=attempt.pk)
    return render(request, "classroom/exam_intro.html", {"exam": exam, "can_start": available(exam)})


@student_only
@require_POST
def exam_start(request, pk):
    get_object_or_404(Exam, pk=pk, published=True, course__enrollments__student=request.user)
    try:
        attempt = start_attempt(pk, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect("exam_intro", pk=pk)
    return redirect("attempt", pk=attempt.pk)


@student_only
def attempt_view(request, pk):
    get_object_or_404(Attempt, pk=pk, student=request.user)
    attempt = finalize_expired(pk)
    if attempt.submitted_at:
        return render(
            request,
            "classroom/result.html",
            {"attempt": attempt, "show_results": attempt.exam.results_released and attempt.graded},
        )
    answers = list(attempt.answers.select_related("question"))
    return render(request, "classroom/attempt.html", {"attempt": attempt, "answers": answers})


@student_only
@require_POST
def attempt_save(request, pk):
    get_object_or_404(Attempt, pk=pk, student=request.user)
    try:
        payload = json.loads(request.body)
        if (
            not isinstance(payload, dict)
            or type(payload.get("revision")) is not int
            or type(payload.get("submit", False)) is not bool
            or ("flags" in payload and not isinstance(payload["flags"], dict))
        ):
            raise ValueError
        attempt = save_answers(
            pk,
            request.user,
            payload.get("answers"),
            payload["revision"],
            payload.get("submit", False),
            payload.get("flags", {}),
        )
    except (ValueError, TypeError, UnicodeDecodeError, ValidationError):
        return JsonResponse({"error": "Invalid answers. Your previously saved work is safe."}, status=400)
    except RevisionConflict:
        return JsonResponse(
            {"error": "This attempt changed in another tab. Reload before continuing."}, status=409
        )
    return JsonResponse(
        {
            "revision": attempt.revision,
            "submitted": bool(attempt.submitted_at),
            "url": reverse("attempt", args=[pk]),
        }
    )


def finish_overdue(exam):
    for pk in exam.attempts.filter(submitted_at__isnull=True, deadline_at__lte=timezone.now()).values_list(
        "pk", flat=True
    ):
        finalize_expired(pk)


@teacher_only
def gradebook(request, pk):
    exam = get_object_or_404(
        Exam.objects.prefetch_related("questions").select_related("course"),
        pk=pk,
        course__teacher=request.user,
    )
    finish_overdue(exam)
    rows = gradebook_rows(exam)
    complete = [row.attempt for row in rows if row.status == "graded"]
    query, status = gradebook_filters(request)
    filtered = filter_rows(rows, query, status)
    page = Paginator(filtered, 25).get_page(request.GET.get("page"))
    stats = [
        ("Submissions", sum(bool(row.attempt and row.attempt.submitted_at) for row in rows)),
        ("Awaiting review", sum(row.status == "needs_review" for row in rows)),
        ("Not started", sum(row.status == "not_started" for row in rows)),
        (
            "Class average",
            f"{round(sum(a.percentage for a in complete) / len(complete))}%" if complete else "—",
        ),
    ]
    return render(
        request,
        "classroom/gradebook.html",
        {
            "exam": exam,
            "rows": page,
            "stats": stats,
            "query": query,
            "status": status,
            "status_choices": STATUSES.items(),
            "total_students": len(rows),
            "filtered_count": len(filtered),
            "filter_query": urlencode({"q": query, "status": status}),
        },
    )


def gradebook_filters(request):
    query = request.GET.get("q", "").strip()[:150]
    status = request.GET.get("status", "")
    return query, status if status in STATUSES else ""


@teacher_only
def review(request, pk):
    attempt = get_object_or_404(Attempt, pk=pk, exam__course__teacher=request.user)
    attempt = finalize_expired(pk)
    if not attempt.submitted_at:
        messages.error(request, "This student is still taking the exam.")
        return redirect("gradebook", pk=attempt.exam_id)
    written = list(attempt.answers.filter(question__kind=Question.Kind.TEXT).select_related("question"))
    form = forms.Form(request.POST if request.method == "POST" else None)
    for answer in written:
        form.fields[f"points_{answer.pk}"] = forms.IntegerField(
            min_value=0,
            max_value=answer.question.points,
            initial=answer.awarded_points,
            label=f"Points for question {answer.question.position + 1}",
        )
        form.fields[f"feedback_{answer.pk}"] = forms.CharField(
            required=False,
            max_length=2000,
            initial=answer.feedback,
            label="Feedback",
            widget=forms.Textarea(attrs={"rows": 2}),
        )
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            Attempt.objects.select_for_update().get(pk=pk)
            for answer in written:
                answer.awarded_points = form.cleaned_data[f"points_{answer.pk}"]
                answer.feedback = form.cleaned_data[f"feedback_{answer.pk}"]
                answer.save(update_fields=["awarded_points", "feedback"])
        messages.success(request, "Grades and feedback saved.")
        return redirect("gradebook", pk=attempt.exam_id)
    return render(request, "classroom/review.html", {"attempt": attempt, "form": form})


@teacher_only
@require_POST
def release_results(request, pk):
    exam = get_object_or_404(Exam, pk=pk, course__teacher=request.user)
    desired = request.POST.get("released")
    if desired not in {"0", "1"}:
        return HttpResponse("Choose whether to release or hide results.", status=400)
    exam.results_released = desired == "1"
    exam.save(update_fields=["results_released"])
    messages.success(
        request,
        "Results released to graded students." if exam.results_released else "Results hidden from students.",
    )
    return redirect("gradebook", pk=pk)


@teacher_only
def export_grades(request, pk):
    exam = get_object_or_404(
        Exam.objects.prefetch_related("questions").select_related("course"),
        pk=pk,
        course__teacher=request.user,
    )
    finish_overdue(exam)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="exam-{exam.pk}-grades.csv"'
    writer = csv.writer(response)
    writer.writerow(["Student", "Username", "Status", "Score", "Maximum", "Percentage"])
    for entry in filter_rows(gradebook_rows(exam), *gradebook_filters(request)):
        a = entry.attempt
        row = [
            entry.student.get_full_name() or entry.student.username,
            entry.student.username,
            entry.status_label,
            a.score if entry.status == "graded" else "",
            exam.total_points,
            a.percentage if entry.status == "graded" else "",
        ]
        writer.writerow(
            [
                "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                for v in row
            ]
        )
    return response
