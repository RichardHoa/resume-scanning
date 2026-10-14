"""
Reference Date: the date prompts treat as "today" when reading and judging a resume set.

It is the real current date unless a run sets an older one (the Tech resume set is from June 2015), so
"2013 - present" in an old resume is counted up to that date instead of the real one.
"""
from datetime import date, datetime
from typing import Optional

# Reference Date of the Tech resume set, passed by --tech runs
TECH_REFERENCE_DATE = "2015-06-30"

_reference_date: Optional[date] = None


def set_reference_date(value: Optional[str]) -> None:
    """Sets the Reference Date for this process from a YYYY-MM-DD string; None or "" goes back to the real date."""
    global _reference_date
    _reference_date = datetime.strptime(value, "%Y-%m-%d").date() if value else None


def get_reference_date() -> date:
    return _reference_date or date.today()


def current_date_prompt_line() -> str:
    """The "Current Date" line prompts open with; an older Reference Date also says the resumes are that old."""
    ref = get_reference_date()
    line = f"Current Date: {ref.strftime('%Y-%m-%d')}."
    if _reference_date is not None:
        month_year = ref.strftime("%B %Y")
        line += (
            f" The resumes in this set were written around {month_year}, not recently. Treat {month_year} as today:"
            f" a role or study marked \"present\", \"now\", \"current\" or \"hiện tại\" ends in {month_year}, and every"
            f" duration, age or recency is counted up to {month_year}. Never judge dates, tools or technologies against"
            f" any later year."
        )
    return line
