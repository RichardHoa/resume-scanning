"""
Report language helpers
"""


def is_english(language: str) -> bool:
    """English output; any other language value means Vietnamese."""
    return language.lower() in ("english", "en")
