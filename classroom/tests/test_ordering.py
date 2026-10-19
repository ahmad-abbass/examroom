from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from classroom.models import Exam, Question
from classroom.services import move_question, publish_exam, start_attempt

from .helpers import ClassroomTestCase


class QuestionOrderingTests(ClassroomTestCase):
    def order(self):
        return list(self.exam.questions.values_list("pk", "position"))

    def test_adjacent_moves_preserve_question_ids_and_contiguous_positions(self):
        self.assertTrue(move_question(self.exam.pk, self.written.pk, self.teacher, "up"))
        self.assertEqual(self.order(), [(self.written.pk, 0), (self.choice.pk, 1)])
        self.assertTrue(move_question(self.exam.pk, self.written.pk, self.teacher, "down"))
        self.assertEqual(self.order(), [(self.choice.pk, 0), (self.written.pk, 1)])

    def test_boundary_moves_and_invalid_requests_do_not_change_order(self):
        before = self.order()
        self.assertFalse(move_question(self.exam.pk, self.choice.pk, self.teacher, "up"))
        self.assertFalse(move_question(self.exam.pk, self.written.pk, self.teacher, "down"))
        for question_id, direction in [(self.choice.pk, "sideways"), (99999, "up")]:
            with self.assertRaises(ValidationError):
                move_question(self.exam.pk, question_id, self.teacher, direction)
        self.assertEqual(self.order(), before)

    def test_published_order_is_frozen_and_attempts_use_the_draft_order(self):
        move_question(self.exam.pk, self.written.pk, self.teacher, "up")
        publish_exam(self.exam.pk, self.teacher)
        attempt = start_attempt(self.exam.pk, self.student)
        self.assertEqual(
            list(attempt.answers.values_list("question_id", flat=True)), [self.written.pk, self.choice.pk]
        )
        with self.assertRaises(PermissionDenied):
            move_question(self.exam.pk, self.choice.pk, self.teacher, "up")

    def test_move_requires_post_teacher_ownership_and_matching_exam(self):
        url = reverse("question_move", args=[self.exam.pk, self.written.pk])
        self.client.force_login(self.student)
        self.assertEqual(self.client.post(url, {"direction": "up"}).status_code, 403)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.post(url, {"direction": "up"}).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 405)
        other = Exam.objects.create(course=self.course, title="Other")
        foreign = Question.objects.create(exam=other, kind="text", prompt="Different")
        self.assertEqual(
            self.client.post(
                reverse("question_move", args=[self.exam.pk, foreign.pk]), {"direction": "up"}
            ).status_code,
            404,
        )
        self.assertRedirects(
            self.client.post(url, {"direction": "up"}), reverse("exam_edit", args=[self.exam.pk])
        )
        self.assertEqual(self.order()[0][0], self.written.pk)

    def test_append_after_reordering_and_deleting_keeps_contiguous_positions(self):
        self.client.force_login(self.teacher)
        move_question(self.exam.pk, self.written.pk, self.teacher, "up")
        self.client.post(reverse("question_delete", args=[self.exam.pk, self.choice.pk]))
        self.client.post(
            reverse("question_create", args=[self.exam.pk]),
            {"kind": "text", "prompt": "New question", "points": 5},
        )
        self.assertEqual(list(self.exam.questions.values_list("position", flat=True)), [0, 1])
