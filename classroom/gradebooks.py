from dataclasses import dataclass

from django.contrib.auth.models import User

from .models import Attempt

STATUSES = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "needs_review": "Needs review",
    "graded": "Graded",
}


@dataclass(frozen=True)
class GradebookRow:
    student: User
    attempt: Attempt | None
    status: str

    @property
    def status_label(self):
        return STATUSES[self.status]


def gradebook_rows(exam):
    students = {
        enrollment.student_id: enrollment.student
        for enrollment in exam.course.enrollments.select_related("student")
    }
    attempts = {}
    for attempt in exam.attempts.select_related("student").prefetch_related("answers"):
        attempt.exam = exam
        attempts[attempt.student_id] = attempt
        students.setdefault(attempt.student_id, attempt.student)
    rows = []
    for student in students.values():
        attempt = attempts.get(student.pk)
        status = "not_started"
        if attempt:
            status = (
                "graded" if attempt.graded else ("needs_review" if attempt.submitted_at else "in_progress")
            )
        rows.append(GradebookRow(student, attempt, status))
    return sorted(
        rows,
        key=lambda row: ((row.student.get_full_name() or row.student.username).casefold(), row.student.pk),
    )


def filter_rows(rows, query, status):
    query = query.casefold()
    return [
        row
        for row in rows
        if (not status or row.status == status)
        and (
            not query
            or query in row.student.get_full_name().casefold()
            or query in row.student.username.casefold()
        )
    ]
