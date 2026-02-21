import os
import sys
from pathlib import Path

base_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(base_dir))

from main import create_app

application = create_app()
