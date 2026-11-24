from celery import Celery
from celery.signals import worker_process_init

from backend.app_factory import create_app
from backend.db.models import db


def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=app.config.get("CELERY_RESULT_BACKEND"),
        broker=app.config.get("CELERY_BROKER_URL"),
    )
    celery.conf.update(
        imports=("backend.services.tasks", "backend.services.automation_worker"),
        beat_schedule={"poll-automations": {"task": "remind.automation.poll", "schedule": 15.0}},
        worker_prefetch_multiplier=1,
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


app = create_app()
celery = make_celery(app)


@worker_process_init.connect
def reset_worker_database_connections(**_):
    with app.app_context():
        db.engine.dispose(close=False)
