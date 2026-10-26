from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from classroom.models import Answer, Attempt, Exam, Question
from classroom.services import move_question, publish_exam, save_answers, start_attempt

from .helpers import ClassroomTestCase


class ExamPreviewTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse("exam_preview", args=[self.exam.pk])
        self.client.force_login(self.teacher)

    def test_owner_can_try_draft_without_answer_keys_or_an_attempt(self):
        self.exam.instructions = "Read each question carefully."
        self.exam.save()
        response = self.client.get(self.url)
        self.assertContains(response, self.exam.instructions)
        self.assertContains(response, self.choice.prompt)
        self.assertContains(response, self.written.prompt)
        for option in self.choice.options:
            self.assertContains(response, option)
        self.assertContains(response, 'type="radio"', count=4)
        self.assertContains(response, 'maxlength="10000"', count=1)
        self.assertContains(response, "Preview only. Answers are not saved or submitted.")
        self.assertNotContains(response, self.choice.explanation)
        self.assertNotContains(response, "✓ Correct")
        self.assertNotContains(response, "correct_option")
        self.assertNotContains(response, "data-save-url")
        self.assertNotContains(response, 'id="submit-exam"')
        self.assertNotContains(response, "checked")
        self.assertEqual(Attempt.objects.count(), 0)
        self.assertEqual(Answer.objects.count(), 0)

    def test_preview_requires_sign_in_teacher_role_and_exam_ownership(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"/login/?next={self.url}")
        for user in [self.student, self.other_student]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("exam_preview", args=[99999])).status_code, 404)

    def test_preview_and_rejected_post_leave_responses_and_grades_unchanged(self):
        publish_exam(self.exam.pk, self.teacher)
        attempt = start_attempt(self.exam.pk, self.student)
        save_answers(
            attempt.pk,
            self.student,
            {str(self.choice.pk): 1, str(self.written.pk): "A private student response"},
            0,
            submit=True,
        )
        answer = attempt.answers.get(question=self.written)
        answer.awarded_points = 17
        answer.feedback = "Private teacher feedback"
        answer.save()
        models = [Exam, Question, Attempt, Answer]
        before = [list(model.objects.order_by("pk").values()) for model in models]
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, answer.text)
        self.assertNotContains(response, answer.feedback)
        self.assertNotContains(response, "checked")
        self.assertEqual(self.client.head(self.url).status_code, 200)
        self.assertEqual(
            self.client.post(self.url, {f"question_{self.written.pk}": "Preview"}).status_code,
            405,
        )
        self.assertEqual(before, [list(model.objects.order_by("pk").values()) for model in models])

    def test_owner_can_preview_a_published_exam_after_its_window(self):
        publish_exam(self.exam.pk, self.teacher)
        Exam.objects.filter(pk=self.exam.pk).update(closes_at=timezone.now() - timedelta(hours=1))
        self.assertContains(self.client.get(self.url), self.choice.prompt)
        self.assertEqual(Attempt.objects.count(), 0)

    def test_preview_preserves_order_and_escapes_content(self):
        move_question(self.exam.pk, self.written.pk, self.teacher, "up")
        self.written.refresh_from_db()
        self.written.prompt = '<script>alert("question")</script>'
        self.written.save()
        self.exam.instructions = "<script>alert('instructions')</script>"
        self.exam.save()
        page = self.client.get(self.url).content.decode()
        self.assertLess(
            page.index(f'id="question-{self.written.pk}"'), page.index(f'id="question-{self.choice.pk}"')
        )
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn(self.written.prompt, page)
        self.assertNotIn(self.exam.instructions, page)

    def test_empty_draft_has_a_path_back_to_the_builder(self):
        self.exam.questions.all().delete()
        response = self.client.get(self.url)
        self.assertContains(response, "No questions to preview yet.")
        self.assertContains(response, reverse("exam_edit", args=[self.exam.pk]))
        self.assertEqual(Attempt.objects.count(), 0)

    def test_builder_links_to_preview(self):
        response = self.client.get(reverse("exam_edit", args=[self.exam.pk]))
        self.assertContains(response, f'href="{self.url}">Preview as student</a>')

    def test_shared_student_inputs_retain_saved_choice_zero_and_escaped_text(self):
        publish_exam(self.exam.pk, self.teacher)
        attempt = start_attempt(self.exam.pk, self.student)
        save_answers(
            attempt.pk,
            self.student,
            {str(self.choice.pk): 0, str(self.written.pk): "<b>A saved answer</b>"},
            0,
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse("attempt", args=[attempt.pk]))
        self.assertContains(response, 'value="0" checked')
        self.assertContains(response, "&lt;b&gt;A saved answer&lt;/b&gt;")
        self.assertContains(response, "data-save-url")
        self.assertNotContains(response, "Preview only.")
