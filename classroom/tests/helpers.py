from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from classroom.models import Course, Enrollment, Exam, Question


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class ClassroomTestCase(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user("teacher", first_name="Leila")
        self.teacher.profile.role = "teacher"
        self.teacher.profile.save()
        self.other_teacher = User.objects.create_user("other-teacher")
        self.other_teacher.profile.role = "teacher"
        self.other_teacher.profile.save()
        self.student = User.objects.create_user("student", first_name="Ahmad")
        self.other_student = User.objects.create_user("other-student", first_name="Maya")
        self.course = Course.objects.create(teacher=self.teacher, name="Algorithms", code="CS301")
        Enrollment.objects.create(course=self.course, student=self.student)
        self.exam = Exam.objects.create(course=self.course, title="Search strategies", duration_minutes=30)
        self.choice = Question.objects.create(
            exam=self.exam,
            prompt="Binary search complexity?",
            options=["O(1)", "O(log n)", "O(n)", "O(n squared)"],
            correct_option=1,
            explanation="The remaining range is halved.",
        )
        self.written = Question.objects.create(
            exam=self.exam, position=1, kind="text", prompt="Explain the invariant.", points=20
        )
