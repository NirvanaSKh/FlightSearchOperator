import datetime

def convert_to_iso_date(date_str):
    """Converts contextual dates like 'tomorrow', 'next Friday', or 'in 5 days' to YYYY-MM-DD."""
    
    today = datetime.date.today()

    if date_str.lower() == "tomorrow":
        return (today + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

    if "in " in date_str and " days" in date_str:
        try:
            days = int(date_str.split("in ")[1].split(" days")[0])
            return (today + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        except:
            return date_str  # If parsing fails, return original text

    if "next" in date_str.lower():
        weekdays = {
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6
        }
        for day in weekdays:
            if day in date_str.lower():
                today_weekday = today.weekday()
                target_weekday = weekdays[day]
                days_until_next = (target_weekday - today_weekday + 7) % 7
                if days_until_next == 0:
                    days_until_next += 7  # If today is already the target day, move to next week
                return (today + datetime.timedelta(days=days_until_next)).strftime("%Y-%m-%d")

    try:
        return datetime.datetime.strptime(date_str + f" {today.year}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return date_str  # Return original if conversion fails
