from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from classroom.models import Exam, Question
from classroom.services import duplicate_exam, start_attempt

from .helpers import ClassroomTestCase


class ExamDuplicationTests(ClassroomTestCase):
    def test_copy_keeps_questions_but_resets_schedule_results_and_attempts(self):
        self.exam.published = True
        self.exam.results_released = True
        self.exam.opens_at = timezone.now() - timedelta(hours=1)
        self.exam.closes_at = timezone.now() + timedelta(hours=1)
        self.exam.save()
        start_attempt(self.exam.pk, self.student)
        draft = duplicate_exam(self.exam.pk, self.teacher)
        self.assertEqual(draft.course, self.course)
        self.assertEqual(draft.title, "Search strategies (copy)")
        self.assertEqual(draft.duration_minutes, 30)
        self.assertFalse(draft.published)
        self.assertFalse(draft.results_released)
        self.assertIsNone(draft.opens_at)
        self.assertIsNone(draft.closes_at)
        self.assertFalse(draft.attempts.exists())
        fields = ["position", "kind", "prompt", "points", "options", "correct_option", "explanation"]
        self.assertEqual(list(draft.questions.values(*fields)), list(self.exam.questions.values(*fields)))
        copied = draft.questions.first()
        copied.prompt = "A different assessment"
        copied.save()
        self.choice.refresh_from_db()
        self.assertEqual(self.choice.prompt, "Binary search complexity?")

    def test_copy_route_is_post_only_and_scoped_to_the_owner(self):
        url = reverse("exam_duplicate", args=[self.exam.pk])
        for user, status in [(self.student, 403), (self.other_teacher, 404)]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(url).status_code, status)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        draft = Exam.objects.exclude(pk=self.exam.pk).get()
        self.assertRedirects(response, reverse("exam_edit", args=[draft.pk]))

    def test_empty_draft_and_maximum_length_title_can_be_copied(self):
        self.exam.title = "x" * 160
        self.exam.save()
        Question.objects.filter(exam=self.exam).delete()
        draft = duplicate_exam(self.exam.pk, self.teacher)
        self.assertEqual(len(draft.title), 160)
        self.assertFalse(draft.questions.exists())

    def test_students_cannot_see_the_copied_draft(self):
        draft = duplicate_exam(self.exam.pk, self.teacher)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("exam_intro", args=[draft.pk])).status_code, 404)
