import json

from django.urls import reverse

from classroom.models import Question
from classroom.services import publish_exam, start_attempt

from .helpers import ClassroomTestCase


class LargeSaveTests(ClassroomTestCase):
    def test_full_fifty_question_utf8_payload_fits_the_request_limit(self):
        self.choice.delete()
        Question.objects.bulk_create(
            [
                Question(exam=self.exam, position=position, kind="text", prompt=f"Written {position}")
                for position in range(2, 51)
            ]
        )
        publish_exam(self.exam.pk, self.teacher)
        attempt = start_attempt(self.exam.pk, self.student)
        text = "漢" * 10000
        answers = {str(question.pk): text for question in self.exam.questions.all()}
        payload = json.dumps({"answers": answers, "revision": 0}, ensure_ascii=False)
        self.assertEqual(len(answers), 50)
        self.assertGreater(len(payload.encode()), 1_200_000)
        self.client.force_login(self.student)
        response = self.client.post(
            reverse("attempt_save", args=[attempt.pk]), payload, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(attempt.answers.filter(text=text).count(), 50)

    def test_large_utf8_answer_set_saves_and_submits_without_truncation(self):
        for position in range(2, 5):
            Question.objects.create(
                exam=self.exam, position=position, kind="text", prompt=f"Written {position}"
            )
        publish_exam(self.exam.pk, self.teacher)
        attempt = start_attempt(self.exam.pk, self.student)
        text = "ن" * 10000
        answers = {str(question.pk): text for question in self.exam.questions.filter(kind="text")}
        payload = json.dumps({"answers": answers, "flags": {}, "revision": 0}, ensure_ascii=False)
        self.assertGreater(len(payload.encode()), 65536)
        self.client.force_login(self.student)
        url = reverse("attempt_save", args=[attempt.pk])
        response = self.client.post(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 200)
        for answer in attempt.answers.filter(question__kind="text"):
            self.assertEqual(answer.text, text)
        response = self.client.post(
            url,
            json.dumps({"answers": answers, "revision": 1, "submit": True}, ensure_ascii=False),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["submitted"])
