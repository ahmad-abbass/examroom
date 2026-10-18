import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Provision a teacher account. Password comes from a prompt or TEACHER_PASSWORD."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", required=True)
        parser.add_argument("--email", required=True)

    def handle(self, *args, **options):
        User = get_user_model()
        if User.objects.filter(username=options["username"]).exists():
            raise CommandError("That username already exists. No account was changed.")
        password = os.environ.get("TEACHER_PASSWORD") or getpass.getpass("Teacher password: ")
        user = User(username=options["username"], first_name=options["name"], email=options["email"])
        try:
            user.full_clean(exclude=["password"])
            validate_password(password, user)
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from error
        user.set_password(password)
        user.save()
        user.profile.role = "teacher"
        user.profile.save()
        self.stdout.write(self.style.SUCCESS(f"Teacher {user.username} created."))
