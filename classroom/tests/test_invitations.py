from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.urls import reverse

from classroom.models import Enrollment
from classroom.services import update_invitation

from .helpers import ClassroomTestCase


class InvitationTests(ClassroomTestCase):
    def test_pausing_blocks_new_students_but_preserves_existing_access(self):
        update_invitation(self.course.pk, self.teacher, "close")
        self.client.force_login(self.other_student)
        response = self.client.post(reverse("course_join"), {"code": self.course.join_code}, follow=True)
        self.assertContains(response, "New joins are paused")
        self.assertFalse(Enrollment.objects.filter(student=self.other_student).exists())
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse("course", args=[self.course.pk])).status_code, 200)
        self.assertTrue(Enrollment.objects.filter(student=self.student, course=self.course).exists())

    def test_reopening_is_idempotent_and_allows_a_join(self):
        for action in ["close", "close", "open", "open"]:
            update_invitation(self.course.pk, self.teacher, action)
        self.client.force_login(self.other_student)
        self.client.post(reverse("course_join"), {"code": self.course.join_code})
        self.assertTrue(Enrollment.objects.filter(student=self.other_student, course=self.course).exists())

    def test_rotation_invalidates_old_code_without_changing_pause_state(self):
        old_code = self.course.join_code
        update_invitation(self.course.pk, self.teacher, "close")
        updated = update_invitation(self.course.pk, self.teacher, "rotate")
        self.assertNotEqual(updated.join_code, old_code)
        self.assertFalse(updated.join_enabled)
        update_invitation(self.course.pk, self.teacher, "open")
        self.client.force_login(self.other_student)
        self.client.post(reverse("course_join"), {"code": old_code})
        self.assertFalse(Enrollment.objects.filter(student=self.other_student).exists())
        self.client.post(reverse("course_join"), {"code": updated.join_code})
        self.assertTrue(Enrollment.objects.filter(student=self.other_student).exists())

    def test_repeated_random_codes_fail_without_changing_the_invitation(self):
        with patch("classroom.services.join_code", return_value=self.course.join_code):
            with self.assertRaises(ValidationError):
                update_invitation(self.course.pk, self.teacher, "rotate")
        self.course.refresh_from_db()
        self.assertTrue(self.course.join_enabled)

    def test_only_the_owner_can_change_invitations_with_post(self):
        url = reverse("course_invitation", args=[self.course.pk])
        for user, status in [(self.other_teacher, 404), (self.student, 403)]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(url, {"action": "rotate"}).status_code, status)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(
            self.client.post(url, {"action": "invalid"}), reverse("course", args=[self.course.pk])
        )
        self.course.refresh_from_db()
        self.assertTrue(self.course.join_enabled)
        self.assertRedirects(
            self.client.post(url, {"action": "close"}), reverse("course", args=[self.course.pk])
        )
        self.course.refresh_from_db()
        self.assertFalse(self.course.join_enabled)
