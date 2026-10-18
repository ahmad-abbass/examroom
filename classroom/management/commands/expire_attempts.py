from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.models import Attempt
from classroom.services import finalize_expired


class Command(BaseCommand):
    help = "Finalize overdue attempts. Safe to run periodically or more than once."

    def handle(self, *args, **options):
        ids = list(
            Attempt.objects.filter(submitted_at__isnull=True, deadline_at__lte=timezone.now()).values_list(
                "pk", flat=True
            )
        )
        for pk in ids:
            finalize_expired(pk)
        self.stdout.write(f"Finalized {len(ids)} overdue attempt(s).")
