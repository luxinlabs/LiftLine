import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DATA_DIR', '/tmp/liftline')
os.environ.setdefault('MODE', 'demo')

from lift_agent.config import Config
from lift_agent.server import handler_for
from lift_agent.store import Store

config = Config.from_env()
store = Store(config.data_dir)
store.initialize()
store.seed(datetime.now(timezone.utc))  # ephemeral synthetic data per cold start
handler = handler_for(store, config)
