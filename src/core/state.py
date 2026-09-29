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
        # In-memory background batch-evaluation jobs keyed by job id (not persisted across restarts)
        self.eval_jobs: Dict[str, Dict[str, Any]] = {}


state = AppState()
