from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from classroom.models import Answer, Attempt, BankQuestion, Exam, Question
from classroom.services import add_bank_question, save_answers, save_question_to_bank, start_attempt

from .helpers import ClassroomTestCase


class QuestionBankTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        self.bank = BankQuestion.objects.create(
            teacher=self.teacher,
            title="Search complexity",
            topic="Graphs",
            **self.choice.content_values(),
        )
        self.foreign = BankQuestion.objects.create(
            teacher=self.other_teacher,
            title="Private answer key",
            kind="text",
            prompt="Another teacher's question",
        )
        self.client.force_login(self.teacher)

    def form_data(self, **changes):
        data = {
            "title": "Traversal order",
            "topic": "Graphs",
            "kind": "choice",
            "prompt": "Which structure supports breadth-first traversal?",
            "points": 15,
            "option_a": " Queue ",
            "option_b": "Stack",
            "option_c": "Heap",
            "option_d": "Tree",
            "correct_option": "0",
            "explanation": "Visit vertices in discovery order.",
        }
        return {**data, **changes}

    def test_create_validated_choice_and_text_questions_with_server_owned_identity(self):
        response = self.client.post(
            reverse("bank_question_create"), self.form_data(teacher=self.other_teacher.pk)
        )
        self.assertRedirects(response, reverse("question_bank"))
        created = BankQuestion.objects.get(title="Traversal order")
        self.assertEqual(created.teacher, self.teacher)
        self.assertEqual(created.options, ["Queue", "Stack", "Heap", "Tree"])
        self.assertEqual(created.correct_option, 0)
        response = self.client.post(
            reverse("bank_question_create"),
            self.form_data(title="Explain BFS", kind="text", option_a="", correct_option=""),
        )
        self.assertEqual(response.status_code, 302)
        written = BankQuestion.objects.get(title="Explain BFS")
        self.assertEqual(written.options, [])
        self.assertIsNone(written.correct_option)

    def test_invalid_content_never_creates_a_bank_question(self):
        for changes in [
            {"title": " "},
            {"title": "t" * 161},
            {"topic": "t" * 81},
            {"prompt": "p" * 3001},
            {"option_a": " "},
            {"option_d": "x" * 501},
            {"correct_option": ""},
            {"correct_option": "9"},
            {"points": 0},
            {"points": 101},
            {"kind": "unknown"},
        ]:
            with self.subTest(changes=changes):
                response = self.client.post(reverse("bank_question_create"), self.form_data(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertEqual(BankQuestion.objects.count(), 2)

    def test_edit_preserves_choices_and_cannot_reassign_the_owner(self):
        url = reverse("bank_question_edit", args=[self.bank.pk])
        response = self.client.get(url)
        self.assertEqual(response.context["form"]["option_b"].value(), "O(log n)")
        self.assertRedirects(
            self.client.post(url, self.form_data(teacher=self.other_teacher.pk)), reverse("question_bank")
        )
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.teacher, self.teacher)
        self.assertEqual(self.bank.title, "Traversal order")
        self.assertEqual(self.bank.options[0], "Queue")

    def test_bank_routes_require_a_teacher_and_do_not_reveal_other_teachers_questions(self):
        routes = [
            ("get", reverse("question_bank")),
            ("get", reverse("bank_question_create")),
            ("get", reverse("bank_question_edit", args=[self.bank.pk])),
            ("post", reverse("bank_question_delete", args=[self.bank.pk])),
            ("post", reverse("question_to_bank", args=[self.exam.pk, self.choice.pk])),
            ("post", reverse("bank_question_add", args=[self.exam.pk, self.bank.pk])),
        ]
        for user in [None, self.student]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for method, url in routes:
                with self.subTest(user=user, method=method, url=url):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 403 if user else 302)
                    if not user:
                        self.assertTrue(response.url.startswith(reverse("login") + "?next="))
        self.client.force_login(self.other_teacher)
        for method, url in routes[2:]:
            self.assertEqual(getattr(self.client, method)(url).status_code, 404)
        response = self.client.get(reverse("question_bank"))
        self.assertContains(response, "Private answer key")
        self.assertNotContains(response, "Search complexity")
        self.assertEqual(BankQuestion.objects.count(), 2)
        self.assertEqual(self.exam.questions.count(), 2)

    def test_mutating_routes_are_post_only_and_csrf_protected(self):
        for url in [
            reverse("bank_question_delete", args=[self.bank.pk]),
            reverse("question_to_bank", args=[self.exam.pk, self.choice.pk]),
            reverse("bank_question_add", args=[self.exam.pk, self.bank.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.teacher)
        client.get(reverse("question_bank"))
        url = reverse("bank_question_add", args=[self.exam.pk, self.bank.pk])
        self.assertEqual(client.post(url).status_code, 403)
        self.assertEqual(self.exam.questions.count(), 2)
        self.assertEqual(
            client.post(url, HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value).status_code, 302
        )
        self.assertEqual(self.exam.questions.count(), 3)

    def test_save_from_published_exam_copies_content_without_changing_attempts(self):
        self.exam.published = True
        self.exam.save()
        attempt = start_attempt(self.exam.pk, self.student)
        before = list(attempt.answers.values())
        response = self.client.post(reverse("question_to_bank", args=[self.exam.pk, self.choice.pk]))
        saved = BankQuestion.objects.exclude(pk__in=[self.bank.pk, self.foreign.pk]).get()
        self.assertRedirects(response, reverse("bank_question_edit", args=[saved.pk]))
        self.assertEqual(saved.content_values(), self.choice.content_values())
        self.assertEqual(saved.teacher, self.teacher)
        self.assertEqual(list(attempt.answers.values()), before)
        self.assertEqual(self.exam.questions.count(), 2)
        self.choice.prompt = "changed source"
        self.choice.save()
        saved.refresh_from_db()
        self.assertEqual(saved.prompt, "Binary search complexity?")

    def test_saved_title_normalizes_whitespace_and_respects_length_limit(self):
        self.choice.prompt = " \n " + "Long question " * 30
        self.choice.save()
        saved = save_question_to_bank(self.exam.pk, self.choice.pk, self.teacher)
        self.assertEqual(saved.title, " ".join(self.choice.prompt.split())[:160])
        self.assertEqual(saved.prompt, self.choice.prompt)

    def test_copy_appends_questions_in_order_with_independent_values(self):
        copied = add_bank_question(self.exam.pk, self.bank.pk, self.teacher)
        second = add_bank_question(self.exam.pk, self.bank.pk, self.teacher)
        self.assertNotEqual(copied.pk, second.pk)
        self.assertEqual((copied.position, second.position), (2, 3))
        self.assertEqual(copied.content_values(), self.bank.content_values())
        copied.options[0] = "Edited exam option"
        copied.save()
        self.assertEqual(self.bank.options[0], "O(1)")
        self.bank.refresh_from_db()
        self.assertEqual(self.bank.options[0], "O(1)")
        second.refresh_from_db()
        self.assertEqual(second.options[0], "O(1)")

    def test_copy_rejects_foreign_questions_and_exams(self):
        foreign_exam = Exam.objects.create(
            course=self.other_teacher.teaching.create(name="Other", code="OTHER"), title="Other exam"
        )
        for exam_id, bank_id in [(self.exam.pk, self.foreign.pk), (foreign_exam.pk, self.bank.pk)]:
            response = self.client.post(reverse("bank_question_add", args=[exam_id, bank_id]))
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.exam.questions.count(), 2)
        self.assertEqual(foreign_exam.questions.count(), 0)

    def test_copy_blocks_published_exams_and_drafts_with_existing_attempts(self):
        self.exam.published = True
        self.exam.save()
        with self.assertRaises(PermissionDenied):
            add_bank_question(self.exam.pk, self.bank.pk, self.teacher)
        self.assertEqual(
            self.client.post(reverse("bank_question_add", args=[self.exam.pk, self.bank.pk])).status_code, 403
        )
        start_attempt(self.exam.pk, self.student)
        self.exam.published = False
        self.exam.save()
        with self.assertRaises(PermissionDenied):
            add_bank_question(self.exam.pk, self.bank.pk, self.teacher)
        self.assertEqual(self.exam.questions.count(), 2)

    def test_fiftieth_question_is_allowed_and_fifty_first_is_rejected_atomically(self):
        Question.objects.bulk_create(
            [Question(exam=self.exam, position=i, kind="text", prompt=f"Question {i}") for i in range(2, 49)]
        )
        self.assertEqual(add_bank_question(self.exam.pk, self.bank.pk, self.teacher).position, 49)
        before = list(self.exam.questions.values())
        with self.assertRaisesMessage(ValidationError, "at most 50"):
            add_bank_question(self.exam.pk, self.bank.pk, self.teacher)
        response = self.client.post(
            reverse("bank_question_add", args=[self.exam.pk, self.bank.pk]), follow=True
        )
        self.assertContains(response, "An exam can contain at most 50 questions.")
        self.assertEqual(list(self.exam.questions.values()), before)
        picker = self.client.get(reverse("question_bank"), {"exam": self.exam.pk})
        self.assertTrue(picker.context["exam_full"])
        self.assertContains(picker, "disabled>Add to exam</button>")

    def test_bank_edits_and_deletion_leave_published_copies_and_grading_unchanged(self):
        exam = Exam.objects.create(course=self.course, title="Reused question")
        copied = add_bank_question(exam.pk, self.bank.pk, self.teacher)
        before = copied.content_values()
        exam.published = True
        exam.save()
        attempt = start_attempt(exam.pk, self.student)
        self.client.post(
            reverse("bank_question_edit", args=[self.bank.pk]), self.form_data(correct_option="3")
        )
        self.assertRedirects(
            self.client.post(reverse("bank_question_delete", args=[self.bank.pk])), reverse("question_bank")
        )
        copied.refresh_from_db()
        self.assertEqual(copied.content_values(), before)
        save_answers(attempt.pk, self.student, {str(copied.pk): 1}, revision=0, submit=True)
        self.assertEqual(Answer.objects.get(attempt=attempt).awarded_points, 10)
        self.assertEqual(exam.questions.count(), 1)

    def test_search_filters_and_pagination_remain_private_and_keep_exam_context(self):
        BankQuestion.objects.bulk_create(
            [
                BankQuestion(
                    teacher=self.teacher,
                    title=f"Traversal {i:02d}",
                    topic="Graphs",
                    kind="text",
                    prompt="Visit vertices",
                )
                for i in range(14)
            ]
        )
        BankQuestion.objects.filter(teacher=self.teacher, kind="text").update(updated_at=timezone.now())
        url = reverse("question_bank")
        response = self.client.get(url, {"q": "gRaPhS", "kind": "text", "exam": self.exam.pk})
        self.assertEqual(response.context["questions"].paginator.count, 14)
        self.assertEqual(len(response.context["questions"]), 12)
        self.assertEqual(response.context["questions"][0].title, "Traversal 13")
        self.assertContains(response, "kind=text")
        self.assertContains(response, f"exam={self.exam.pk}")
        self.assertNotContains(response, "Private answer key")
        self.assertNotContains(response, "Search complexity")
        page = self.client.get(url, {"q": "Graphs", "kind": "text", "exam": self.exam.pk, "page": 2})
        self.assertEqual([q.title for q in page.context["questions"]], ["Traversal 01", "Traversal 00"])
        for query in ["complexity", "halved", "Binary search"]:
            result = self.client.get(url, {"q": query})
            self.assertEqual(result.context["questions"].paginator.count, 0 if query == "halved" else 1)

    def test_picker_rejects_foreign_frozen_and_malformed_exam_ids(self):
        url = reverse("question_bank")
        for value in ["no", "-1", "0", "9" * 100]:
            self.assertEqual(self.client.get(url, {"exam": value}).status_code, 404)
        self.client.force_login(self.other_teacher)
        self.assertEqual(self.client.get(url, {"exam": self.exam.pk}).status_code, 404)
        self.client.force_login(self.teacher)
        self.exam.published = True
        self.exam.save()
        self.assertEqual(self.client.get(url, {"exam": self.exam.pk}).status_code, 403)

    def test_invalid_filters_empty_results_and_html_are_handled_safely(self):
        url = reverse("question_bank")
        for filters in [{"kind": "bogus"}, {"q": "x" * 121}]:
            response = self.client.get(url, filters)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertEqual(response.context["questions"].paginator.count, 0)
        self.bank.title = '<script>alert("private")</script>'
        self.bank.save()
        response = self.client.get(url, {"page": "not-a-page"})
        self.assertEqual(response.context["questions"].number, 1)
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("private")</script>')

    def test_reading_bank_and_picker_creates_no_exam_or_attempt_state(self):
        before = (
            Question.objects.count(),
            Exam.objects.count(),
            Attempt.objects.count(),
            Answer.objects.count(),
        )
        for params in [{}, {"exam": self.exam.pk}]:
            self.assertEqual(self.client.get(reverse("question_bank"), params).status_code, 200)
        self.assertEqual(
            (Question.objects.count(), Exam.objects.count(), Attempt.objects.count(), Answer.objects.count()),
            before,
        )
