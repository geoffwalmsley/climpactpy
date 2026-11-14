"""``climpact-web manage runworker``: run queued jobs until stopped."""

import signal
import threading

from django.core.management.base import BaseCommand

from climpact_web.jobs.worker import JobWorker


class Command(BaseCommand):
    help = (
        "Run queued background jobs (station runs, batches, gridded runs) one at a time, "
        "until stopped with Ctrl+C or SIGTERM. In local mode 'climpact-web' starts one."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true", help="run the jobs waiting now, then exit"
        )
        parser.add_argument(
            "--poll", type=float, default=None, help="seconds between checks for new jobs"
        )
        parser.add_argument("--name", default=None, help="worker name (default host:pid)")
        parser.add_argument("--no-cleanup", action="store_true", help="do not delete expired jobs")

    def handle(self, *args, once=False, poll=None, name=None, no_cleanup=False, **options):
        worker = JobWorker(name=name, poll=poll, once=once, cleanup=not no_cleanup)
        if threading.current_thread() is threading.main_thread():

            def stop(signum, frame):
                # Finish at the next progress step: the running job is queued again.
                worker.stop.set()

            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            if hasattr(signal, "SIGBREAK"):  # Windows: CTRL_BREAK_EVENT from climpact-web
                signal.signal(signal.SIGBREAK, stop)
        count = worker.run()
        if once:
            self.stdout.write(f"Ran {count} job(s).")
