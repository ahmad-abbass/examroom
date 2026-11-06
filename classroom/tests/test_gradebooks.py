import csv
import io
from datetime import timedelta

from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from classroom.gradebooks import SORTS, gradebook_rows, sort_rows
from classroom.models import Attempt, Enrollment, Exam
from classroom.services import publish_exam, save_answers, start_attempt

from .helpers import ClassroomTestCase


class GradebookTests(ClassroomTestCase):
    def setUp(self):
        super().setUp()
        publish_exam(self.exam.pk, self.teacher)
        Enrollment.objects.create(course=self.course, student=self.other_student)
        self.active = User.objects.create_user("active", first_name="Omar")
        self.graded_student = User.objects.create_user("graded", first_name="Rami")
        for student in [self.active, self.graded_student]:
            Enrollment.objects.create(course=self.course, student=student)
        start_attempt(self.exam.pk, self.active)
        self.pending = self.submit(self.student)
        self.graded_attempt = self.submit(self.graded_student)
        self.graded_attempt.answers.filter(question=self.written).update(awarded_points=20)
        self.client.force_login(self.teacher)

    def submit(self, student):
        attempt = start_attempt(self.exam.pk, student)
        return save_answers(
            attempt.pk, student, {str(self.choice.pk): 1, str(self.written.pk): "Invariant"}, 0, True
        )

    def test_roster_includes_every_status_and_stats_are_not_filtered(self):
        response = self.client.get(reverse("gradebook", args=[self.exam.pk]), {"status": "not_started"})
        rows = list(response.context["rows"])
        self.assertEqual(
            [(row.student.pk, row.status) for row in rows], [(self.other_student.pk, "not_started")]
        )
        self.assertEqual(response.context["total_students"], 4)
        self.assertEqual(
            dict(response.context["stats"]),
            {"Submissions": 2, "Awaiting review": 1, "Not started": 1, "Class average": "100%"},
        )
        self.assertContains(response, "Maya")
        self.assertNotContains(response, "Rami")

    def test_search_matches_names_or_usernames_and_combines_with_status(self):
        url = reverse("gradebook", args=[self.exam.pk])
        for query, status, expected in [
            ("AHMAD", "needs_review", self.student),
            ("GrAdEd", "graded", self.graded_student),
            ("Omar", "in_progress", self.active),
        ]:
            response = self.client.get(url, {"q": query, "status": status})
            self.assertEqual([row.student.pk for row in response.context["rows"]], [expected.pk])
        response = self.client.get(url, {"q": "Ahmad", "status": "graded"})
        self.assertEqual(response.context["filtered_count"], 0)
        response = self.client.get(url, {"status": "forged"})
        self.assertEqual(response.context["filtered_count"], 4)

    def test_csv_contains_not_started_students_and_obeys_filters(self):
        url = reverse("export_grades", args=[self.exam.pk])
        response = self.client.get(url)
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 5)
        missing = next(row for row in rows[1:] if row[1] == self.other_student.username)
        self.assertEqual(missing[2:], ["Not started", "", "30", ""])
        response = self.client.get(url, {"q": "Rami", "status": "graded"})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][3:], ["30", "30", "100"])

    def test_pagination_is_stable_and_export_is_not_limited_to_one_page(self):
        for index in range(25):
            student = User.objects.create_user(f"extra-{index:02d}", first_name=f"Student {index:02d}")
            Enrollment.objects.create(course=self.course, student=student)
        url = reverse("gradebook", args=[self.exam.pk])
        first = self.client.get(url, {"status": "not_started"})
        second = self.client.get(url, {"status": "not_started", "page": "2"})
        self.assertEqual(len(first.context["rows"]), 25)
        self.assertEqual(len(second.context["rows"]), 1)
        ids = [row.student.pk for row in first.context["rows"]] + [
            row.student.pk for row in second.context["rows"]
        ]
        self.assertEqual(len(set(ids)), 26)
        response = self.client.get(
            reverse("export_grades", args=[self.exam.pk]), {"status": "not_started", "page": "2"}
        )
        self.assertEqual(len(list(csv.reader(io.StringIO(response.content.decode())))), 27)

    def test_gradebook_data_uses_bounded_queries_with_prefetched_answers(self):
        exam = Exam.objects.select_related("course").prefetch_related("questions").get(pk=self.exam.pk)
        with self.assertNumQueries(3):
            rows = gradebook_rows(exam)
            for row in rows:
                if row.status == "graded":
                    self.assertEqual(row.attempt.percentage, 100)
            for order in SORTS:
                self.assertEqual(len(sort_rows(rows, order)), len(rows))

    def test_historical_attempt_remains_visible_after_external_roster_removal(self):
        Enrollment.objects.filter(course=self.course, student=self.graded_student).delete()
        rows = gradebook_rows(self.exam)
        self.assertIn(self.graded_student.pk, [row.student.pk for row in rows])

    def test_score_sorting_keeps_zero_scores_and_places_ungraded_rows_last(self):
        zero = User.objects.create_user("score-zero", first_name="Zero")
        tied = User.objects.create_user("score-tied", first_name="Asha")
        for student, score in [(zero, 0), (tied, 20)]:
            Enrollment.objects.create(course=self.course, student=student)
            attempt = self.submit(student)
            attempt.answers.filter(question=self.written).update(awarded_points=score)
            if student == zero:
                attempt.answers.filter(question=self.choice).update(awarded_points=0)
        ungraded = [self.student.pk, self.other_student.pk, self.active.pk]
        url = reverse("gradebook", args=[self.exam.pk])
        for order, expected in [
            ("score_desc", [tied.pk, self.graded_student.pk, zero.pk] + ungraded),
            ("score_asc", [zero.pk, tied.pk, self.graded_student.pk] + ungraded),
        ]:
            response = self.client.get(url, {"sort": order})
            self.assertEqual([row.student.pk for row in response.context["rows"]], expected)
            self.assertContains(response, f'value="{order}" selected')
            self.assertEqual(dict(response.context["stats"])["Class average"], "67%")

    def test_submission_sorting_includes_pending_reviews_and_puts_missing_dates_last(self):
        now = timezone.now()
        Attempt.objects.filter(pk=self.pending.pk).update(submitted_at=now - timedelta(hours=1))
        Attempt.objects.filter(pk=self.graded_attempt.pk).update(submitted_at=now - timedelta(days=1))
        response = self.client.get(reverse("gradebook", args=[self.exam.pk]), {"sort": "submitted_desc"})
        self.assertEqual(
            [row.student.pk for row in response.context["rows"]],
            [self.student.pk, self.graded_student.pk, self.other_student.pk, self.active.pk],
        )

    def test_sorting_precedes_pagination_and_csv_retains_the_same_filters_and_order(self):
        students = []
        for index in range(27):
            student = User.objects.create_user(f"ranked-{index:02d}", first_name=f"Student {index:02d}")
            Enrollment.objects.create(course=self.course, student=student)
            attempt = self.submit(student)
            points = index % 21
            attempt.answers.filter(question=self.written).update(awarded_points=points)
            students.append((student, 10 + points))
        expected = sorted(students, key=lambda item: (-item[1], item[0].first_name.casefold(), item[0].pk))
        filters = {"q": "ranked-", "status": "graded", "sort": "score_desc"}
        url = reverse("gradebook", args=[self.exam.pk])
        first = self.client.get(url, filters)
        second = self.client.get(url, {**filters, "page": "2"})
        self.assertEqual(len(first.context["rows"]), 25)
        self.assertEqual(len(second.context["rows"]), 2)
        actual = [row.student.pk for row in first.context["rows"]] + [
            row.student.pk for row in second.context["rows"]
        ]
        self.assertEqual(actual, [student.pk for student, _ in expected])
        self.assertContains(first, "sort=score_desc&amp;page=2")
        response = self.client.get(reverse("export_grades", args=[self.exam.pk]), {**filters, "page": "2"})
        rows = list(csv.reader(io.StringIO(response.content.decode())))
        self.assertEqual([row[1] for row in rows[1:]], [student.username for student, _ in expected])
        self.assertEqual([int(row[3]) for row in rows[1:]], [score for _, score in expected])

    def test_unknown_sort_uses_the_default_name_order(self):
        url = reverse("gradebook", args=[self.exam.pk])
        for order in ["", "forged", "-score", "score_desc extra"]:
            response = self.client.get(url, {"sort": order})
            self.assertEqual(response.context["sort"], "name")
            self.assertEqual(
                [row.student.pk for row in response.context["rows"]],
                [self.student.pk, self.other_student.pk, self.active.pk, self.graded_student.pk],
            )

    def test_sorted_gradebook_and_csv_keep_teacher_ownership_checks(self):
        for user, status in [(self.student, 403), (self.other_teacher, 404)]:
            self.client.force_login(user)
            for name in ["gradebook", "export_grades"]:
                response = self.client.get(reverse(name, args=[self.exam.pk]), {"sort": "score_desc"})
                self.assertEqual(response.status_code, status)
