"""
Application Shared State & Dependencies
"""
from typing import Optional, Any


class AppState:
    """Holds references to initialized server instances and global configuration."""
    def __init__(self):
        self.extractor: Optional[Any] = None
        self.evaluator: Optional[Any] = None
        self.args: Optional[Any] = None
        self.temp_dir: str = ""
        self.static_dir: str = ""


state = AppState()
