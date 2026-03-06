import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(base_dir))


def create_application():
    from main import create_app

    return create_app()


application = create_application()
