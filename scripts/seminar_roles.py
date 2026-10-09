"""Normalize seminar roles without rewriting completed degree descriptions."""
import re


def normalize_role(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r'\bAssociate\s+Professor\b', 'Associate Professor', value, flags=re.I)
    value = re.sub(r'\bPhD\s+Student\b', 'PhD Student', value, flags=re.I)
    return re.sub(r'\bPhD\b(?=\s*(?:@|[,，;；)）]|$))', 'PhD Student', value)
