import json
from datetime import timedelta
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.urls import reverse

from classroom.models import Exam, Question
from classroom.services import RevisionConflict, publish_exam, save_answers, start_attempt

from .helpers import ClassroomTestCase


class ReviewFlagTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        publish_exam(self.exam.pk, self.teacher)
        self.attempt = start_attempt(self.exam.pk, self.student)

    def test_flags_persist_with_answers_and_can_be_cleared_independently(self):
        save_answers(
            self.attempt.pk, self.student, {str(self.choice.pk): 1}, 0, flags={str(self.choice.pk): True}
        )
        answer = self.attempt.answers.get(question=self.choice)
        self.assertTrue(answer.flagged)
        self.assertEqual(answer.selected_option, 1)
        save_answers(self.attempt.pk, self.student, {}, 1, flags={str(self.choice.pk): False})
        answer.refresh_from_db()
        self.assertFalse(answer.flagged)
        self.assertEqual(answer.selected_option, 1)

    def test_stale_flags_cannot_overwrite_current_marks(self):
        save_answers(self.attempt.pk, self.student, {}, 0, flags={str(self.choice.pk): True})
        with self.assertRaises(RevisionConflict):
            save_answers(self.attempt.pk, self.student, {}, 0, flags={str(self.choice.pk): False})
        self.assertTrue(self.attempt.answers.get(question=self.choice).flagged)

    def test_foreign_or_non_boolean_flags_roll_back_answer_changes(self):
        foreign_exam = Exam.objects.create(course=self.course, title="Other")
        foreign = Question.objects.create(exam=foreign_exam, kind="text", prompt="Other")
        for flags in [[], {str(self.choice.pk): 1}, {str(self.choice.pk): "true"}, {str(foreign.pk): True}]:
            with self.assertRaises(ValidationError):
                save_answers(
                    self.attempt.pk, self.student, {str(self.written.pk): "Do not save"}, 0, flags=flags
                )
            self.assertEqual(self.attempt.answers.get(question=self.written).text, "")

    def test_flags_freeze_at_submission_and_do_not_affect_scoring(self):
        save_answers(
            self.attempt.pk,
            self.student,
            {str(self.choice.pk): 1},
            0,
            submit=True,
            flags={str(self.choice.pk): True},
        )
        save_answers(self.attempt.pk, self.student, {}, 1, flags={str(self.choice.pk): False})
        answer = self.attempt.answers.get(question=self.choice)
        self.assertTrue(answer.flagged)
        self.assertEqual(answer.awarded_points, 10)

    def test_late_flag_payload_is_ignored(self):
        with patch(
            "classroom.services.timezone.now", return_value=self.attempt.deadline_at + timedelta(seconds=1)
        ):
            save_answers(self.attempt.pk, self.student, {}, 0, flags={str(self.choice.pk): True})
        self.assertFalse(self.attempt.answers.get(question=self.choice).flagged)

    def test_api_and_rendered_navigation_preserve_saved_flags(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("attempt_save", args=[self.attempt.pk]),
            json.dumps({"answers": {}, "flags": {str(self.written.pk): True}, "revision": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        page = self.client.get(reverse("attempt", args=[self.attempt.pk]))
        self.assertContains(page, "Question navigator")
        self.assertContains(
            page, f'data-flag="{self.written.pk}" aria-label="Mark question 2 for review" aria-pressed="true"'
        )
        self.assertNotContains(page, self.choice.explanation)

    def test_flag_api_retains_attempt_owner_checks(self):
        self.client.force_login(self.other_student)
        response = self.client.post(
            reverse("attempt_save", args=[self.attempt.pk]),
            json.dumps({"answers": {}, "flags": {}, "revision": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_api_rejects_null_flags_without_accepting_answer_changes(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("attempt_save", args=[self.attempt.pk]),
            json.dumps({"answers": {str(self.written.pk): "Rejected"}, "flags": None, "revision": 0}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.attempt.answers.get(question=self.written).text, "")
