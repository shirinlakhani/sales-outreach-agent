import re
import json

def safe_parse_json(text: str):
    """
    Strips markdown code blocks (```json ... ```) and parses the inner JSON content.
    Returns a dictionary or None if parsing fails.
    """
    if not text:
        return None
    try:
        # Remove markdown code block syntax
        clean_text = re.sub(r"```json|```", "", text).strip()
        return json.loads(clean_text)
    except Exception:
        # Fallback for when LLM returns raw text that might contain a JSON-like structure
        try:
            start_idx = text.find('{')
            end_idx = text.rfind('}')
            if start_idx != -1 and end_idx != -1:
                return json.loads(text[start_idx:end_idx + 1])
        except:
            pass
        return None

def sanitize_filename(filename: str):
    """Removes special characters to ensure safe filesystem naming."""
    return re.sub(r'[^\w\s-]', '', filename).strip().replace(' ', '_')