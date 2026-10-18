"""Fictional, local-only sample classrooms. Never runs automatically on deployment."""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from classroom.models import Course, Enrollment, Exam, Question
from classroom.services import save_answers, start_attempt


class Command(BaseCommand):
    help = "Populate an empty development database with fictional demo accounts and exams."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Demo accounts are disabled when DJANGO_DEBUG=0.")
        if User.objects.filter(username="demo.teacher").exists():
            self.stdout.write("Demo already seeded. Existing accounts and work were not changed.")
            return
        if User.objects.exists():
            raise CommandError("Seed an empty development database. Existing users were not changed.")
        now = timezone.now()
        teacher = User.objects.create_user(
            "demo.teacher",
            password="DemoRoom!2026",
            first_name="Leila",
            last_name="Mansour",
            email="teacher@example.test",
        )
        teacher.profile.role = "teacher"
        teacher.profile.save()
        students = [
            User.objects.create_user(
                f"demo.{name.lower()}",
                password="DemoRoom!2026",
                first_name=name,
                email=f"{name.lower()}@example.test",
            )
            for name in ["Ahmad", "Maya", "Omar"]
        ]
        courses = [
            Course.objects.create(teacher=teacher, code=code, name=name, description=description)
            for code, name, description in [
                (
                    "CS201",
                    "Data Structures",
                    "Good structures. Clearer thinking. Explore the ideas behind efficient programs.",
                ),
                ("CS202", "Object-Oriented Programming", "Design thoughtful software, one object at a time."),
                (
                    "MATH201",
                    "Discrete Mathematics",
                    "Patterns, proofs, and the foundations of computer science.",
                ),
            ]
        ]
        for course in courses:
            Enrollment.objects.bulk_create([Enrollment(course=course, student=s) for s in students])

        def exam(course, title, minutes=45, published=True):
            return Exam.objects.create(
                course=course,
                title=title,
                duration_minutes=minutes,
                published=published,
                opens_at=now - timedelta(days=1),
                closes_at=now + timedelta(days=7),
                instructions="Read each question carefully. You can change your answers until you submit. Written responses should explain your reasoning.",
            )

        def choice(exam, prompt, options, correct, explanation, points=10):
            return Question.objects.create(
                exam=exam,
                position=exam.questions.count(),
                prompt=prompt,
                options=options,
                correct_option=correct,
                explanation=explanation,
                points=points,
            )

        midterm = exam(courses[0], "Data Structures · Midterm")
        choice(
            midterm,
            "What is the worst-case lookup time in an AVL tree with n nodes?",
            ["O(1)", "O(log n)", "O(n)", "O(n log n)"],
            1,
            "The AVL balance invariant keeps the tree height logarithmic.",
        )
        choice(
            midterm,
            "Which principle does a stack follow?",
            ["First in, first out", "Last in, first out", "Smallest element first", "Random order"],
            1,
            "A stack removes the most recently added element first.",
        )
        choice(
            midterm,
            "For a well-sized hash table with a suitable hash function, what is the expected lookup time?",
            ["O(1)", "O(log n)", "O(n)", "O(n²)"],
            0,
            "Expected constant time depends on hashing and load-factor assumptions; the worst case can be linear.",
        )
        Question.objects.create(
            exam=midterm,
            position=3,
            kind="text",
            prompt="Explain what an AVL rotation preserves, and why a rotation can help restore balance.",
            points=20,
            explanation="A rotation preserves the in-order sequence (the BST ordering) while changing local heights.",
        )
        oop = exam(courses[1], "Object-oriented thinking", 30)
        choice(
            oop,
            "Which idea keeps an object's internal state behind a public interface?",
            ["Encapsulation", "Compilation", "Recursion", "Sorting"],
            0,
            "Encapsulation defines a boundary between the public interface and internal implementation.",
        )
        choice(
            oop,
            "Why should a polymorphic C++ base class usually have a virtual destructor?",
            [
                "It avoids all allocations",
                "It allows correct destruction through a base pointer",
                "It makes every method static",
                "It disables inheritance",
            ],
            1,
            "Deleting through a base pointer requires a virtual destructor to destroy the derived object correctly.",
        )
        logic = exam(courses[2], "Logic warm-up", 25)
        choice(
            logic,
            "Which expression is equivalent to NOT (A AND B)?",
            ["NOT A AND NOT B", "A OR B", "NOT A OR NOT B", "A AND NOT B"],
            2,
            "This is one of De Morgan's laws.",
        )
        choice(
            logic,
            "How many subsets does a set with 4 elements have?",
            ["4", "8", "12", "16"],
            3,
            "Each element can be included or excluded independently: 2⁴ = 16.",
        )
        choice(
            logic,
            "What is the contrapositive of 'if P then Q'?",
            ["If Q then P", "If NOT Q then NOT P", "If NOT P then NOT Q", "P AND Q"],
            1,
            "An implication is logically equivalent to its contrapositive.",
        )
        logic.results_released = True
        logic.save()
        draft = exam(courses[0], "Trees & traversal", 20, False)
        choice(
            draft,
            "Which traversal visits a binary search tree in sorted order?",
            ["Pre-order", "In-order", "Post-order", "Level-order"],
            1,
            "The in-order traversal processes left subtree, node, then right subtree.",
        )
        for student, corrects in [(students[1], [1, 0, 0]), (students[2], [1, 1, 0])]:
            attempt = start_attempt(midterm.pk, student)
            questions = list(midterm.questions.all())
            payload = {str(q.pk): value for q, value in zip(questions[:3], corrects)}
            payload[str(questions[3].pk)] = (
                "The in-order ordering is unchanged. A local rotation moves a child up and redistributes subtrees to reduce an excessive height difference."
            )
            attempt = save_answers(attempt.pk, student, payload, 0, True)
            if student == students[2]:
                answer = attempt.answers.get(question=questions[3])
                answer.awarded_points = 17
                answer.feedback = "Clear reasoning. Mention which subtree heights change to make the explanation even more precise."
                answer.save()
        attempt = start_attempt(logic.pk, students[0])
        save_answers(
            attempt.pk,
            students[0],
            {str(q.pk): answer for q, answer in zip(logic.questions.all(), [2, 3, 0])},
            0,
            True,
        )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo ready. Teacher: demo.teacher · Student: demo.ahmad · Password: DemoRoom!2026"
            )
        )
