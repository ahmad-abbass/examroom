from django.core.exceptions import ValidationError
from django.urls import reverse

from classroom.models import Answer
from classroom.services import RevisionConflict, grade_submission, publish_exam, save_answers, start_attempt

from .helpers import ClassroomTestCase


class GradingRevisionTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        publish_exam(self.exam.pk, self.teacher)
        self.attempt = start_attempt(self.exam.pk, self.student)
        save_answers(self.attempt.pk, self.student, {str(self.written.pk): "The invariant holds."}, 0, True)
        self.answer = self.attempt.answers.get(question=self.written)

    def test_stale_review_does_not_replace_saved_points_or_feedback(self):
        grade_submission(self.attempt.pk, self.teacher, {self.answer.pk: (18, "Saved feedback")}, 0)
        with self.assertRaises(RevisionConflict):
            grade_submission(self.attempt.pk, self.teacher, {self.answer.pk: (2, "Stale feedback")}, 0)
        self.answer.refresh_from_db()
        self.assertEqual((self.answer.awarded_points, self.answer.feedback), (18, "Saved feedback"))
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.grading_revision, 1)
        self.assertEqual(self.attempt.revision, 1)

    def test_current_revision_can_update_a_review(self):
        grade_submission(self.attempt.pk, self.teacher, {self.answer.pk: (10, "First")}, 0)
        grade_submission(self.attempt.pk, self.teacher, {self.answer.pk: (19, "Revised")}, 1)
        self.answer.refresh_from_db()
        self.assertEqual(self.answer.awarded_points, 19)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.grading_revision, 2)

    def test_invalid_or_incomplete_grades_do_not_change_existing_work(self):
        invalid = [
            {},
            {self.answer.pk: (21, "Too many")},
            {self.answer.pk: (True, "Boolean")},
            {self.answer.pk: (5, "x" * 2001)},
            {99999: (5, "Foreign")},
        ]
        for grades in invalid:
            with self.assertRaises(ValidationError):
                grade_submission(self.attempt.pk, self.teacher, grades, 0)
            self.assertIsNone(Answer.objects.get(pk=self.answer.pk).awarded_points)
        self.attempt.refresh_from_db()
        self.assertEqual(self.attempt.grading_revision, 0)

    def test_service_rejects_foreign_teacher_and_unsubmitted_attempt(self):
        from classroom.models import Attempt

        with self.assertRaises(Attempt.DoesNotExist):
            grade_submission(self.attempt.pk, self.other_teacher, {self.answer.pk: (5, "Foreign")}, 0)
        self.attempt.submitted_at = None
        self.attempt.save()
        with self.assertRaises(ValidationError):
            grade_submission(self.attempt.pk, self.teacher, {self.answer.pk: (5, "Early")}, 0)

    def test_http_conflict_preserves_newer_grade_and_requires_reload(self):
        self.client.force_login(self.teacher)
        url = reverse("review", args=[self.attempt.pk])
        first = self.client.get(url)
        self.assertContains(first, 'name="grading_revision" value="0"')
        data = {"grading_revision": 0, f"points_{self.answer.pk}": 17, f"feedback_{self.answer.pk}": "Latest"}
        self.assertRedirects(self.client.post(url, data), reverse("gradebook", args=[self.exam.pk]))
        data[f"points_{self.answer.pk}"] = 1
        conflict = self.client.post(url, data)
        self.assertContains(conflict, "saved in another tab", status_code=409)
        self.assertContains(conflict, "Reload latest review", status_code=409)
        self.assertEqual(Answer.objects.get(pk=self.answer.pk).awarded_points, 17)
        self.assertContains(self.client.get(url), 'name="grading_revision" value="1"')

    def test_missing_revision_does_not_bypass_the_review_guard(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse("review", args=[self.attempt.pk]), {f"points_{self.answer.pk}": 15}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(Answer.objects.get(pk=self.answer.pk).awarded_points)
