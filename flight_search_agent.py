import re
import datetime

def convert_to_iso_date(date_str):
    """Convert natural language dates like 'tomorrow', 'in 3 days', or '5th May' to YYYY-MM-DD format."""
    today = datetime.date.today()
    if not date_str or not isinstance(date_str, str) or date_str.strip() == "":
        return None  # Trigger clarification

    date_str = date_str.lower().strip()

    if date_str == "tomorrow":
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    # Handle "in X days"
    match = re.search(r"in (\d+) days", date_str)
    if match:
        days = int(match.group(1))
        return (today + datetime.timedelta(days=days)).strftime("%Y-%m-%d")

    # Remove ordinal suffixes (1st, 2nd, 3rd, 4th)
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str)

    # Try different date formats
    formats = [
        "%d %B %Y",  # "5 May 2024"
        "%B %d %Y",  # "May 5 2024"
        "%d %b %Y",  # "5 May 2024"
        "%b %d %Y",  # "May 5 2024"
        "%d/%m/%Y",  # "05/05/2024"
        "%m/%d/%Y",  # "05/05/2024"
        "%d-%m-%Y",  # "05-05-2024"
        "%m-%d-%Y"   # "05-05-2024"
    ]

    for fmt in formats:
        try:
            return datetime.datetime.strptime(f"{date_str} {today.year}", fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue  # Try next format

    return None  # Trigger clarification
