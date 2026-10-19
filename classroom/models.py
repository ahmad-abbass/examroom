import secrets

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


def join_code():
    return secrets.token_hex(4).upper()


class Profile(models.Model):
    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        TEACHER = "teacher", "Teacher"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)


class LoginThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    failures = models.PositiveIntegerField(default=0)
    since = models.DateTimeField()


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


class Course(models.Model):
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teaching")
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=24)
    description = models.TextField(blank=True, max_length=1000)
    join_code = models.CharField(max_length=8, unique=True, default=join_code, editable=False)
    join_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Enrollment(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="enrollments")
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments"
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["course", "student"], name="unique_enrollment")]


class Exam(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="exams")
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True, max_length=4000)
    duration_minutes = models.PositiveIntegerField(
        default=45, validators=[MinValueValidator(1), MaxValueValidator(240)]
    )
    opens_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False)
    results_released = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def total_points(self):
        return sum(q.points for q in self.questions.all())

    def __str__(self):
        return self.title


class Question(models.Model):
    class Kind(models.TextChoices):
        CHOICE = "choice", "Multiple choice"
        TEXT = "text", "Written response"

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="questions")
    position = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.CHOICE)
    prompt = models.TextField(max_length=3000)
    points = models.PositiveIntegerField(
        default=10, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    options = models.JSONField(default=list, blank=True)
    correct_option = models.PositiveSmallIntegerField(null=True, blank=True)
    explanation = models.TextField(blank=True, max_length=2000)

    class Meta:
        ordering = ["position", "pk"]


class Attempt(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attempts")
    started_at = models.DateTimeField()
    deadline_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    timed_out = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam", "student"], name="one_attempt_per_student")]
        ordering = ["-started_at"]

    @property
    def graded(self):
        return self.submitted_at is not None and not self.answers.filter(awarded_points__isnull=True).exists()

    @property
    def score(self):
        return sum(a.awarded_points or 0 for a in self.answers.all())

    @property
    def percentage(self):
        total = self.exam.total_points
        return round(100 * self.score / total) if total else 0


class Answer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    selected_option = models.PositiveSmallIntegerField(null=True, blank=True)
    text = models.TextField(blank=True, max_length=10000)
    awarded_points = models.PositiveIntegerField(null=True, blank=True)
    feedback = models.TextField(blank=True, max_length=2000)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["attempt", "question"], name="one_answer_per_question")
        ]
        ordering = ["question__position", "question__pk"]
