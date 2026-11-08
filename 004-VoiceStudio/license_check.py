"""Inspect model licence state; never create or bypass acceptance records."""
import argparse
import json
import urllib.error
import urllib.parse
import urllib.request


def check(base_url: str, repo_id: str) -> dict:
    path = "/models/licenses/acceptance/" + urllib.parse.quote(repo_id, safe="/")
    url = base_url.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:3900")
    parser.add_argument("--repo-id", default="k2-fsa/OmniVoice")
    args = parser.parse_args()
    try:
        status = check(args.url, args.repo_id)
    except (urllib.error.URLError, TimeoutError) as exc:
        parser.exit(2, f"Unable to query licence status: {exc}\n")
    print(json.dumps(status, indent=2, ensure_ascii=False))
    if not status.get("accepted"):
        parser.exit(3, "Accept the current model terms in VoiceStudio Model Catalogue first.\n")


if __name__ == "__main__":
    main()
