"""Validation and bounded request handling."""
from urllib.parse import urlparse


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Expected a valid http(s) video URL")
    if parsed.username or parsed.password:
        raise ValueError("Credentials must not appear in URL")
    return url


def public_metadata(info: dict) -> dict:
    """Return a limited metadata summary; never echo headers or credentials."""
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "extractor": info.get("extractor_key"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url"),
        "available_formats": len(info.get("formats") or []),
        "downloaded": False,
    }
