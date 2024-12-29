from datetime import timedelta

def parse_duration(duration: str):
    unit = duration[-1]
    value = int(duration[:-1])
    units = {
        "m": "minutes",
        "h": "hours",
        "d": "days",
        "w": "weeks",
        "y": "years",
    }
    return timedelta(**{units[unit]: value})
