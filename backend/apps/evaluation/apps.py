from django.apps import AppConfig


class EvaluationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.evaluation'
    verbose_name = 'Evaluation'

    def ready(self):
        import os
        import threading
        # Run recovery only in the main web server process to avoid doing it
        # during migrations or management commands (like collectstatic).
        if os.environ.get('RUN_MAIN') == 'true' or 'gunicorn' in os.environ.get('SERVER_SOFTWARE', '') or os.environ.get('WAITRESS') == 'true':
            from .pdf_worker import recover_pending_tasks
            threading.Thread(target=recover_pending_tasks, daemon=True).start()
