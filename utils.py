import re
from datetime import datetime, timedelta

# --- Cutoff date helper ---
def get_cutoff_date(days_ago: int | str = 180) -> str:
    """
    Returns a string cutoff date YYYY-MM-DD for N days ago.
    Accepts int or string input. Defaults to 180 days.
    """
    try:
        days = int(days_ago)  # Convert string to int if needed
    except (ValueError, TypeError):
        days = 180  # fallback to default if conversion fails
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

# --- Filename sanitizer ---
def sanitize_filename(name: str) -> str:
    """
    Replace invalid characters with underscores
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)

# --- Text truncation ---
def truncate_text(text: str, max_len: int) -> str:
    """
    Safely truncate text to prevent exceeding LLM token limits
    """
    return text[:max_len] if len(text) > max_len else text