"""
Operation Duration Tracking

Records the wall-clock duration of successful long-running operations per operation kind
(scrutiny, decompose, save_criteria, extract, evaluate_candidate) in a rolling window persisted
to a small JSON file, so the web waiting screen can estimate time remaining across restarts.
"""
import os
import sys
import json
import statistics
import threading
from typing import Dict, List, Optional

from src.core.config import (
    OPERATION_DURATIONS_PATH,
    OPERATION_DURATION_WINDOW,
    OPERATION_DURATION_DEFAULTS_SECONDS
)

_lock = threading.Lock()
_samples: Optional[Dict[str, List[float]]] = None


def _load_samples() -> Dict[str, List[float]]:
    """Returns the in-memory samples, reading the JSON file on first use. Caller holds _lock."""
    global _samples
    if _samples is None:
        _samples = {}
        if os.path.exists(OPERATION_DURATIONS_PATH):
            try:
                with open(OPERATION_DURATIONS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _samples = {
                        k: [float(x) for x in v if isinstance(x, (int, float))]
                        for k, v in data.items() if isinstance(v, list)
                    }
            except Exception as e:
                print(f"[Durations Warning] Could not read {OPERATION_DURATIONS_PATH}: {e}", file=sys.stderr)
    return _samples


def record_duration(kind: str, seconds: float) -> None:
    """Appends one successful run's duration for an operation kind and persists the window."""
    if seconds is None or seconds < 0:
        return
    with _lock:
        samples = _load_samples()
        window = samples.setdefault(kind, [])
        window.append(round(float(seconds), 3))
        del window[:-OPERATION_DURATION_WINDOW]
        try:
            with open(OPERATION_DURATIONS_PATH, "w", encoding="utf-8") as f:
                json.dump(samples, f, indent=2)
        except Exception as e:
            print(f"[Durations Warning] Could not write {OPERATION_DURATIONS_PATH}: {e}", file=sys.stderr)


def expected_durations() -> Dict[str, float]:
    """Returns the expected seconds per operation kind: median of recent samples, else the config default."""
    with _lock:
        samples = _load_samples()
        kinds = set(OPERATION_DURATION_DEFAULTS_SECONDS) | set(samples)
        expected = {}
        for kind in kinds:
            window = samples.get(kind) or []
            if window:
                expected[kind] = round(statistics.median(window), 2)
            else:
                expected[kind] = OPERATION_DURATION_DEFAULTS_SECONDS.get(kind, 30.0)
        return expected
