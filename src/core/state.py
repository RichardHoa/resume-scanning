"""
Application Shared State & Dependencies
"""
from typing import Optional, Any, Dict


class AppState:
    """Holds references to initialized server instances and global configuration."""
    def __init__(self):
        self.extractor: Optional[Any] = None
        self.evaluator: Optional[Any] = None
        self.args: Optional[Any] = None
        self.temp_dir: str = ""
        self.static_dir: str = ""
        # In-memory Batch jobs (extraction and evaluation) keyed by job id, not persisted across restarts
        self.batch_jobs: Dict[str, Dict[str, Any]] = {}


state = AppState()
