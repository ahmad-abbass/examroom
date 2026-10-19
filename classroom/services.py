"""Exam lifecycle rules. The server owns deadlines, scoring and write revisions."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Answer, Attempt, Enrollment, Exam, Question


class RevisionConflict(Exception):
    pass


@transaction.atomic
def duplicate_exam(exam_id, teacher):
    source = Exam.objects.select_for_update().get(pk=exam_id, course__teacher=teacher)
    draft = Exam.objects.create(
        course=source.course,
        title=f"{source.title[:153]} (copy)",
        instructions=source.instructions,
        duration_minutes=source.duration_minutes,
    )
    Question.objects.bulk_create(
        [
            Question(
                exam=draft,
                position=position,
                kind=question.kind,
                prompt=question.prompt,
                points=question.points,
                options=list(question.options),
                correct_option=question.correct_option,
                explanation=question.explanation,
            )
            for position, question in enumerate(source.questions.all())
        ]
    )
    return draft


@transaction.atomic
def move_question(exam_id, question_id, teacher, direction):
    exam = Exam.objects.select_for_update().get(pk=exam_id, course__teacher=teacher)
    if exam.published:
        raise PermissionDenied("Published questions cannot be reordered.")
    if direction not in {"up", "down"}:
        raise ValidationError("Choose a valid move direction.")
    questions = list(exam.questions.all())
    index = next((i for i, question in enumerate(questions) if question.pk == question_id), None)
    if index is None:
        raise ValidationError("That question does not belong to this exam.")
    destination = index + (-1 if direction == "up" else 1)
    if destination not in range(len(questions)):
        return False
    questions[index], questions[destination] = questions[destination], questions[index]
    for position, question in enumerate(questions):
        question.position = position
    Question.objects.bulk_update(questions, ["position"])
    return True


def available(exam, now=None):
    now = now or timezone.now()
    return (
        exam.published
        and (not exam.opens_at or now >= exam.opens_at)
        and (not exam.closes_at or now < exam.closes_at)
    )


@transaction.atomic
def start_attempt(exam_id, student):
    exam = Exam.objects.select_for_update().get(pk=exam_id)
    if not Enrollment.objects.filter(course=exam.course, student=student).exists():
        raise PermissionDenied
    existing = Attempt.objects.filter(exam=exam, student=student).first()
    if existing:
        return existing
    now = timezone.now()
    if not available(exam, now):
        raise ValidationError("This exam is not open for new attempts.")
    deadline = now + timedelta(minutes=exam.duration_minutes)
    if exam.closes_at:
        deadline = min(deadline, exam.closes_at)
    attempt = Attempt.objects.create(exam=exam, student=student, started_at=now, deadline_at=deadline)
    Answer.objects.bulk_create([Answer(attempt=attempt, question=q) for q in exam.questions.all()])
    return attempt


def _finish(attempt, now, timed_out=False):
    if attempt.submitted_at:
        return
    for answer in attempt.answers.select_related("question"):
        if answer.question.kind == Question.Kind.CHOICE:
            answer.awarded_points = (
                answer.question.points if answer.selected_option == answer.question.correct_option else 0
            )
            answer.save(update_fields=["awarded_points"])
    attempt.submitted_at = min(now, attempt.deadline_at)
    attempt.timed_out = timed_out
    attempt.save(update_fields=["submitted_at", "timed_out"])


@transaction.atomic
def finalize_expired(attempt_id):
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id)
    now = timezone.now()
    if not attempt.submitted_at and now >= attempt.deadline_at:
        _finish(attempt, now, timed_out=True)
    return attempt


@transaction.atomic
def save_answers(attempt_id, student, payload, revision, submit=False):
    attempt = Attempt.objects.select_for_update().get(pk=attempt_id, student=student)
    now = timezone.now()
    if attempt.submitted_at:
        return attempt
    if now >= attempt.deadline_at:
        _finish(attempt, now, timed_out=True)
        return attempt  # Never accept answers arriving after the authoritative deadline.
    if revision != attempt.revision:
        raise RevisionConflict
    answers = {str(a.question_id): a for a in attempt.answers.select_related("question")}
    if not isinstance(payload, dict) or set(payload) - set(answers):
        raise ValidationError("Answers must belong to this exam.")
    for question_id, value in payload.items():
        answer = answers[question_id]
        if answer.question.kind == Question.Kind.CHOICE:
            if value is not None and (
                type(value) is not int or value not in range(len(answer.question.options))
            ):
                raise ValidationError("Choose a valid option.")
            answer.selected_option = value
        else:
            if not isinstance(value, str) or len(value) > 10000:
                raise ValidationError("Written answers must contain at most 10,000 characters.")
            answer.text = value
        answer.save(update_fields=["selected_option", "text"])
    attempt.revision += 1
    attempt.save(update_fields=["revision"])
    if submit:
        _finish(attempt, now)
    return attempt


@transaction.atomic
def publish_exam(exam_id, teacher):
    exam = Exam.objects.select_for_update().get(pk=exam_id, course__teacher=teacher)
    if not exam.questions.exists():
        raise ValidationError("Add at least one question before publishing.")
    for question in exam.questions.all():
        if question.kind == Question.Kind.CHOICE and (
            len(question.options) != 4
            or not all(isinstance(option, str) and option.strip() for option in question.options)
            or type(question.correct_option) is not int
            or question.correct_option not in range(4)
        ):
            raise ValidationError("Every multiple-choice question needs four options and a valid answer key.")
    if exam.closes_at and exam.closes_at <= timezone.now():
        raise ValidationError("Choose a future closing time before publishing.")
    exam.published = True
    exam.save(update_fields=["published"])
    return exam
