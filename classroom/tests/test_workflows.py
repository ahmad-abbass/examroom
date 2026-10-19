import csv
import io
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from classroom.forms import ExamForm, QuestionForm
from classroom.models import Answer, Attempt, Course, Enrollment, Exam, Question
from classroom.services import (
    RevisionConflict,
    available,
    publish_exam,
    save_answers,
    start_attempt,
)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ExamWorkflowTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teacher", password="Teacher!2026")
        self.teacher.profile.role = "teacher"
        self.teacher.profile.save()
        self.other_teacher = User.objects.create_user("other-teacher", password="Teacher!2026")
        self.other_teacher.profile.role = "teacher"
        self.other_teacher.profile.save()
        self.student = User.objects.create_user("student", password="Student!2026", first_name="Student")
        self.other_student = User.objects.create_user("other-student", password="Student!2026")
        self.course = Course.objects.create(teacher=self.teacher, name="Data Structures", code="CS201")
        Enrollment.objects.create(course=self.course, student=self.student)
        self.exam = Exam.objects.create(
            course=self.course, title="Trees", published=True, duration_minutes=30
        )
        self.mcq = Question.objects.create(
            exam=self.exam,
            prompt="Complexity?",
            options=["a", "b", "c", "d"],
            correct_option=1,
            points=10,
            explanation="SECRET_EXPLANATION",
        )
        self.written = Question.objects.create(
            exam=self.exam, kind="text", position=1, prompt="Explain your reasoning", points=20
        )

    def start(self, user=None):
        return start_attempt(self.exam.pk, user or self.student)

    def post_answers(self, attempt, answers, revision=0, submit=False):
        return self.client.post(
            reverse("attempt_save", args=[attempt.pk]),
            json.dumps({"answers": answers, "revision": revision, "submit": submit}),
            content_type="application/json",
        )

    def submit(self):
        attempt = self.start()
        return save_answers(
            attempt.pk,
            self.student,
            {str(self.mcq.pk): 1, str(self.written.pk): "Because of the height invariant."},
            0,
            True,
        )

    def test_anonymous_pages_require_sign_in(self):
        self.assertRedirects(self.client.get("/"), "/login/?next=/", fetch_redirect_response=False)

    def test_register_cannot_self_assign_teacher(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new-student",
                "first_name": "New",
                "email": "new@example.test",
                "password1": "Autumn!Pencil9274",
                "password2": "Autumn!Pencil9274",
                "role": "teacher",
                "is_staff": "true",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new-student")
        self.assertEqual(user.profile.role, "student")
        self.assertFalse(user.is_staff)

    def test_teacher_routes_reject_students(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("course_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("exam_edit", args=[self.exam.pk])).status_code, 403)

    def test_teacher_cannot_access_another_teachers_exam(self):
        self.client.force_login(self.other_teacher)
        for route in ["exam_edit", "gradebook", "export_grades"]:
            self.assertEqual(self.client.get(reverse(route, args=[self.exam.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("exam_publish", args=[self.exam.pk])).status_code, 404)

    def test_student_cannot_access_others_attempt(self):
        attempt = self.start()
        self.client.force_login(self.other_student)
        self.assertEqual(self.client.get(reverse("attempt", args=[attempt.pk])).status_code, 404)
        self.assertEqual(self.post_answers(attempt, {}).status_code, 404)

    def test_non_enrolled_student_cannot_start(self):
        with self.assertRaises(PermissionDenied):
            self.start(self.other_student)
        self.client.force_login(self.other_student)
        self.assertEqual(self.client.get(reverse("exam_intro", args=[self.exam.pk])).status_code, 404)

    def test_join_code_is_case_insensitive_and_idempotent(self):
        self.client.force_login(self.other_student)
        for _ in range(2):
            self.client.post(reverse("course_join"), {"code": self.course.join_code.lower()})
        self.assertEqual(Enrollment.objects.filter(course=self.course, student=self.other_student).count(), 1)

    def test_drafts_are_not_visible_to_students(self):
        self.exam.published = False
        self.exam.save()
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("exam_intro", args=[self.exam.pk])).status_code, 404)
        self.assertNotContains(self.client.get("/"), self.exam.title)

    def test_one_attempt_and_original_deadline_are_preserved(self):
        first = self.start()
        self.exam.duration_minutes = 120
        self.exam.save()
        second = self.start()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.deadline_at, second.deadline_at)
        self.assertEqual(Attempt.objects.count(), 1)

    def test_cannot_start_before_opening_or_at_closing(self):
        now = timezone.now()
        self.exam.opens_at = now + timedelta(hours=1)
        self.exam.save()
        with self.assertRaises(ValidationError):
            self.start()
        self.exam.opens_at = None
        self.exam.closes_at = now
        self.exam.save()
        self.assertFalse(available(self.exam, now))
        with self.assertRaises(ValidationError):
            self.start()

    def test_exam_close_shortens_attempt_deadline(self):
        self.exam.closes_at = timezone.now() + timedelta(minutes=5)
        self.exam.save()
        self.assertEqual(self.start().deadline_at, self.exam.closes_at)

    def test_intro_and_attempt_do_not_leak_answer_key(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("exam_intro", args=[self.exam.pk]))
        self.assertNotContains(response, "Complexity?")
        attempt = self.start()
        response = self.client.get(reverse("attempt", args=[attempt.pk]))
        self.assertContains(response, "Complexity?")
        self.assertNotContains(response, "SECRET_EXPLANATION")
        self.assertNotContains(response, "correct_option")
        self.assertNotContains(response, "awarded_points")

    def test_autosave_persists_answers_and_advances_revision(self):
        attempt = self.start()
        self.client.force_login(self.student)
        response = self.post_answers(attempt, {str(self.mcq.pk): 1, str(self.written.pk): "An invariant."})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["revision"], 1)
        self.assertEqual(attempt.answers.get(question=self.written).text, "An invariant.")
        self.assertIsNone(attempt.answers.get(question=self.mcq).awarded_points)
        self.assertNotIn("score", response.json())

    def test_stale_revision_cannot_overwrite_saved_answers(self):
        attempt = self.start()
        save_answers(attempt.pk, self.student, {str(self.mcq.pk): 1}, 0)
        with self.assertRaises(RevisionConflict):
            save_answers(attempt.pk, self.student, {str(self.mcq.pk): 0}, 0)
        self.client.force_login(self.student)
        self.assertEqual(self.post_answers(attempt, {str(self.mcq.pk): 0}, revision=0).status_code, 409)
        self.assertEqual(attempt.answers.get(question=self.mcq).selected_option, 1)

    def test_invalid_choice_is_rejected_atomically(self):
        attempt = self.start()
        with self.assertRaises(ValidationError):
            save_answers(
                attempt.pk, self.student, {str(self.written.pk): "Should roll back", str(self.mcq.pk): 99}, 0
            )
        self.assertEqual(attempt.answers.get(question=self.written).text, "")

    def test_boolean_is_not_a_choice_index(self):
        attempt = self.start()
        with self.assertRaises(ValidationError):
            save_answers(attempt.pk, self.student, {str(self.mcq.pk): True}, 0)

    def test_foreign_question_is_rejected(self):
        attempt = self.start()
        other_exam = Exam.objects.create(course=self.course, title="Other exam")
        other_question = Question.objects.create(exam=other_exam, prompt="Not yours", kind="text")
        with self.assertRaises(ValidationError):
            save_answers(attempt.pk, self.student, {str(other_question.pk): "forged"}, 0)

    def test_oversized_written_response_is_rejected(self):
        attempt = self.start()
        with self.assertRaises(ValidationError):
            save_answers(attempt.pk, self.student, {str(self.written.pk): "a" * 10001}, 0)

    def test_malformed_payload_does_not_crash_or_change_data(self):
        attempt = self.start()
        self.client.force_login(self.student)
        for payload in [
            "not json",
            "[]",
            '{"answers": {}, "revision": true}',
            '{"answers": null, "revision": 0}',
            '{"answers": {}, "revision": 0, "submit": "yes"}',
        ]:
            response = self.client.post(
                reverse("attempt_save", args=[attempt.pk]), payload, content_type="application/json"
            )
            self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.revision, 0)

    def test_late_answers_are_ignored_and_saved_work_is_scored(self):
        attempt = self.start()
        save_answers(attempt.pk, self.student, {str(self.mcq.pk): 1}, 0)
        late = attempt.deadline_at + timedelta(seconds=1)
        with patch("classroom.services.timezone.now", return_value=late):
            result = save_answers(
                attempt.pk, self.student, {str(self.mcq.pk): 0, str(self.written.pk): "Late"}, 1, True
            )
        self.assertTrue(result.timed_out)
        self.assertEqual(result.submitted_at, attempt.deadline_at)
        self.assertEqual(result.answers.get(question=self.mcq).awarded_points, 10)
        self.assertEqual(result.answers.get(question=self.written).text, "")

    def test_exact_deadline_is_already_expired(self):
        attempt = self.start()
        with patch("classroom.services.timezone.now", return_value=attempt.deadline_at):
            result = save_answers(attempt.pk, self.student, {str(self.mcq.pk): 1}, 0, True)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.answers.get(question=self.mcq).awarded_points, 0)

    def test_expiry_command_is_idempotent(self):
        attempt = self.start()
        Attempt.objects.filter(pk=attempt.pk).update(deadline_at=timezone.now() - timedelta(seconds=1))
        for _ in range(2):
            call_command("expire_attempts", stdout=io.StringIO())
        attempt.refresh_from_db()
        self.assertTrue(attempt.timed_out)
        self.assertIsNotNone(attempt.submitted_at)

    def test_submitted_answers_are_immutable_and_resubmission_is_idempotent(self):
        attempt = self.submit()
        result = save_answers(attempt.pk, self.student, {str(self.mcq.pk): 0}, 1, True)
        self.assertEqual(result.submitted_at, attempt.submitted_at)
        self.assertEqual(result.answers.get(question=self.mcq).awarded_points, 10)

    def test_unanswered_multiple_choice_gets_zero(self):
        attempt = self.start()
        save_answers(attempt.pk, self.student, {}, 0, True)
        self.assertEqual(attempt.answers.get(question=self.mcq).awarded_points, 0)

    def test_results_require_both_release_and_completed_manual_grading(self):
        attempt = self.submit()
        self.client.force_login(self.student)
        url = reverse("attempt", args=[attempt.pk])
        self.assertNotContains(self.client.get(url), "SECRET_EXPLANATION")
        self.exam.results_released = True
        self.exam.save()
        self.assertNotContains(self.client.get(url), "SECRET_EXPLANATION")
        Answer.objects.filter(attempt=attempt, question=self.written).update(
            awarded_points=15, feedback="Useful reasoning"
        )
        response = self.client.get(url)
        self.assertContains(response, "SECRET_EXPLANATION")
        self.assertContains(response, "Useful reasoning")
        self.assertContains(response, "25")

    def test_manual_grading_bounds_and_owner_permissions(self):
        attempt = self.submit()
        answer = attempt.answers.get(question=self.written)
        url = reverse("review", args=[attempt.pk])
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(url, {f"points_{answer.pk}": 20}).status_code, 404)
        self.client.force_login(self.teacher)
        for points in [-1, 21]:
            self.assertEqual(
                self.client.post(url, {f"points_{answer.pk}": points, "grading_revision": 0}).status_code, 200
            )
            self.assertIsNone(Answer.objects.get(pk=answer.pk).awarded_points)
        self.assertEqual(
            self.client.post(
                url, {f"points_{answer.pk}": 18, f"feedback_{answer.pk}": "Good", "grading_revision": 0}
            ).status_code,
            302,
        )
        self.assertEqual(Answer.objects.get(pk=answer.pk).awarded_points, 18)

    def test_teacher_cannot_review_an_active_attempt(self):
        attempt = self.start()
        self.client.force_login(self.teacher)
        self.assertRedirects(
            self.client.get(reverse("review", args=[attempt.pk])), reverse("gradebook", args=[self.exam.pk])
        )

    def test_cannot_publish_empty_or_already_closed_exam(self):
        self.exam.published = False
        self.exam.closes_at = timezone.now() - timedelta(hours=1)
        self.exam.save()
        with self.assertRaises(ValidationError):
            publish_exam(self.exam.pk, self.teacher)
        self.exam.questions.all().delete()
        self.exam.closes_at = None
        self.exam.save()
        with self.assertRaises(ValidationError):
            publish_exam(self.exam.pk, self.teacher)

    def test_published_questions_and_timing_cannot_be_modified(self):
        self.client.force_login(self.teacher)
        self.assertEqual(
            self.client.post(
                reverse("exam_edit", args=[self.exam.pk]), {"title": "Changed", "duration_minutes": 200}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(reverse("question_delete", args=[self.exam.pk, self.mcq.pk])).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("question_edit", args=[self.exam.pk, self.mcq.pk])).status_code, 403
        )
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.duration_minutes, 30)
        self.assertTrue(Question.objects.filter(pk=self.mcq.pk).exists())

    def test_teacher_can_build_and_publish_draft(self):
        draft = Exam.objects.create(course=self.course, title="New exam")
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("question_create", args=[draft.pk]),
            {
                "kind": "choice",
                "prompt": "Which option?",
                "points": 5,
                "correct_option": 2,
                "option_a": "A",
                "option_b": "B",
                "option_c": "C",
                "option_d": "D",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.client.post(reverse("exam_publish", args=[draft.pk]))
        draft.refresh_from_db()
        self.assertTrue(draft.published)

    def test_question_form_requires_four_options_and_a_key(self):
        form = QuestionForm(
            {"kind": "choice", "prompt": "Q", "points": 5, "option_a": "A", "correct_option": ""}
        )
        self.assertFalse(form.is_valid())

    def test_exam_form_rejects_invalid_window(self):
        form = ExamForm(
            {
                "title": "Invalid",
                "duration_minutes": 30,
                "opens_at": "2027-02-03T10:00",
                "closes_at": "2027-02-03T09:00",
            }
        )
        self.assertFalse(form.is_valid())

    def test_csv_neutralizes_spreadsheet_formulas(self):
        self.student.first_name = "=HYPERLINK(1)"
        self.student.save()
        self.submit()
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("export_grades", args=[self.exam.pk]))
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(rows[1][0], "'=HYPERLINK(1)")

    def test_csrf_is_required_for_answer_changes_and_start(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.student)
        self.assertEqual(csrf_client.post(reverse("exam_start", args=[self.exam.pk])).status_code, 403)
        attempt = self.start()
        self.assertEqual(
            csrf_client.post(
                reverse("attempt_save", args=[attempt.pk]),
                json.dumps({"answers": {}, "revision": 0}),
                content_type="application/json",
            ).status_code,
            403,
        )

    def test_login_throttle_and_safe_redirect(self):
        for _ in range(8):
            self.client.post(reverse("login"), {"username": "student", "password": "wrong"})
        self.assertEqual(
            self.client.post(reverse("login"), {"username": "student", "password": "wrong"}).status_code, 429
        )
        other = Client()
        response = other.post(
            reverse("login"),
            {"username": "teacher", "password": "Teacher!2026", "next": "https://evil.example"},
        )
        self.assertRedirects(response, "/")

    def test_student_content_is_html_escaped(self):
        attempt = self.submit()
        Answer.objects.filter(attempt=attempt, question=self.written).update(
            text='<script>alert("x")</script>'
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse("review", args=[attempt.pk]))
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("x")</script>')

    def test_release_is_post_only_and_owner_only(self):
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("release_results", args=[self.exam.pk])).status_code, 405)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(reverse("release_results", args=[self.exam.pk])).status_code, 404)

    def test_release_retries_keep_the_requested_state(self):
        self.client.force_login(self.teacher)
        url = reverse("release_results", args=[self.exam.pk])
        for _ in range(2):
            self.assertEqual(self.client.post(url, {"released": "1"}).status_code, 302)
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.results_released)
        self.client.post(url, {"released": "0"})
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.results_released)

    def test_teacher_dashboard_class_and_gradebook_render(self):
        self.client.force_login(self.teacher)
        for url in [
            "/",
            reverse("course", args=[self.course.pk]),
            reverse("exam_edit", args=[self.exam.pk]),
            reverse("gradebook", args=[self.exam.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 200)


@override_settings(DEBUG=True, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class DemoTests(TestCase):
    def test_seed_is_repeatable_without_changing_existing_answers(self):
        output = io.StringIO()
        call_command("seed_demo", stdout=output)
        counts = (User.objects.count(), Exam.objects.count(), Answer.objects.count())
        call_command("seed_demo", stdout=output)
        self.assertEqual(counts, (User.objects.count(), Exam.objects.count(), Answer.objects.count()))
        self.assertTrue(User.objects.get(username="demo.teacher").check_password("DemoRoom!2026"))

    @override_settings(DEBUG=False)
    def test_seed_is_disabled_in_production(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("seed_demo", stdout=io.StringIO())
