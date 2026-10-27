from django.core.management.base import BaseCommand

from orders.services import expire_stale_reservations


class Command(BaseCommand):
    help = (
        "Cancel unpaid M-Pesa/card orders whose stock hold has expired and return "
        "the stock to the shelf. Schedule this every 5 minutes (e.g. a Render cron job)."
    )

    def handle(self, *args, **options):
        count = expire_stale_reservations()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} stale order(s)."))