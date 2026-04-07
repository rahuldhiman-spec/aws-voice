#!/usr/bin/env python3
import argparse
import json
import shlex
import sys
from pathlib import Path


ENV_KEYS = {
    "KNOWLEDGE_BACKEND_URL",
    "KNOWLEDGE_BACKEND_KIND",
    "KNOWLEDGE_BACKEND_NAME",
    "SEARCHUNIFY_UID",
    "SEARCHUNIFY_ACCESS_TOKEN",
    "SEARCHUNIFY_SID",
    "SEARCHUNIFY_SEARCH_UID",
    "SEARCHUNIFY_COOKIE",
    "SEARCHUNIFY_ORIGIN",
    "SEARCHUNIFY_REFERER",
    "SEARCHUNIFY_RESULTS_PER_PAGE",
    "SEARCHUNIFY_LANGUAGE",
    "SEARCHUNIFY_SORTBY",
    "SEARCHUNIFY_ORDER_BY",
}


def _quote_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(char.isspace() for char in value) or any(char in value for char in ['"', "'", ";", "#"]):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _parse_curl(raw: str) -> tuple[str, dict[str, str], dict[str, object]]:
    normalized = raw.replace("\\\n", " ").replace("\\\r\n", " ")
    tokens = shlex.split(normalized, posix=True)
    if not tokens or tokens[0] != "curl":
        raise ValueError("Input does not look like a curl command.")

    url = ""
    headers: dict[str, str] = {}
    body = {}
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-H", "--header"} and index + 1 < len(tokens):
            header_value = tokens[index + 1]
            if ":" in header_value:
                key, value = header_value.split(":", 1)
                headers[key.strip().lower()] = value.strip()
            index += 2
            continue
        if token in {"--data-raw", "--data", "--data-binary"} and index + 1 < len(tokens):
            body = json.loads(tokens[index + 1])
            index += 2
            continue
        if token.startswith("http://") or token.startswith("https://"):
            url = token
        index += 1

    if not url:
        raise ValueError("Could not find the SearchUnify URL in the curl command.")
    return url, headers, body


def _build_updates(url: str, headers: dict[str, str], body: dict[str, object]) -> dict[str, str]:
    updates = {
        "KNOWLEDGE_BACKEND_URL": url,
        "KNOWLEDGE_BACKEND_KIND": "searchunify_post",
        "KNOWLEDGE_BACKEND_NAME": "SearchUnify",
        "SEARCHUNIFY_UID": str(body.get("uid") or ""),
        "SEARCHUNIFY_ACCESS_TOKEN": str(body.get("accessToken") or ""),
        "SEARCHUNIFY_SID": str(body.get("sid") or ""),
        "SEARCHUNIFY_SEARCH_UID": str(body.get("searchUid") or ""),
        "SEARCHUNIFY_COOKIE": headers.get("cookie", ""),
        "SEARCHUNIFY_ORIGIN": headers.get("origin", ""),
        "SEARCHUNIFY_REFERER": headers.get("referer", ""),
        "SEARCHUNIFY_RESULTS_PER_PAGE": str(body.get("resultsPerPage") or body.get("pageSize") or ""),
        "SEARCHUNIFY_LANGUAGE": str(body.get("language") or ""),
        "SEARCHUNIFY_SORTBY": str(body.get("sortby") or ""),
        "SEARCHUNIFY_ORDER_BY": str(body.get("orderBy") or ""),
    }
    return {key: value for key, value in updates.items() if key in ENV_KEYS and value is not None}


def _update_env_file(env_path: Path, updates: dict[str, str]) -> list[str]:
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            new_lines.append(f"{key}={_quote_env_value(updates[key])}")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={_quote_env_value(value)}")

    env_path.write_text("\n".join(new_lines).rstrip() + "\n")
    return sorted(updates.keys())


def main() -> int:
    parser = argparse.ArgumentParser(description="Import SearchUnify curl settings into a .env file.")
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--input-file", help="Optional file containing the copied curl command.")
    args = parser.parse_args()

    if args.input_file:
        raw = Path(args.input_file).read_text()
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            raise SystemExit("No curl command received on stdin. Pipe it in or use --input-file.")

    url, headers, body = _parse_curl(raw)
    updates = _build_updates(url, headers, body)
    updated_keys = _update_env_file(Path(args.env_file), updates)
    print("Updated keys:")
    for key in updated_keys:
        print(f"- {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
