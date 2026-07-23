#!/usr/bin/env python3
"""Generate a committed GitHub profile stats card from public REST data."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


def api_get(path: str, token: str | None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-stats-generator",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = Request(f"{API_ROOT}{path}", headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"GitHub API request failed with HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError("GitHub API request failed") from error


def owned_repositories(username: str, token: str | None) -> list[dict[str, object]]:
    repositories: list[dict[str, object]] = []
    page = 1
    while True:
        query = urlencode(
            {"type": "owner", "sort": "updated", "per_page": 100, "page": page}
        )
        batch = api_get(f"/users/{username}/repos?{query}", token)
        if not isinstance(batch, list):
            raise RuntimeError("GitHub returned an unexpected repositories response")
        repositories.extend(batch)
        if len(batch) < 100:
            return repositories
        page += 1


def authored_items(
    username: str, item_type: str, token: str | None
) -> tuple[int, list[dict[str, object]]]:
    items: list[dict[str, object]] = []
    page = 1
    total_count = 0
    while True:
        query = urlencode(
            {
                "q": f"author:{username} type:{item_type} is:public",
                "sort": "created",
                "order": "desc",
                "per_page": 100,
                "page": page,
            }
        )
        payload = api_get(f"/search/issues?{query}", token)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError("GitHub returned an unexpected search response")
        if payload.get("incomplete_results"):
            raise RuntimeError("GitHub returned incomplete search results")
        total_count = int(payload.get("total_count", 0))
        batch = payload["items"]
        items.extend(batch)
        if len(items) >= min(total_count, 1000) or len(batch) < 100:
            return total_count, items
        page += 1


def render_svg(metrics: list[tuple[str, int]]) -> str:
    rows = []
    for index, (label, value) in enumerate(metrics):
        y = 70 + index * 24
        rows.append(
            f'<circle cx="31" cy="{y - 5}" r="3" fill="#586e75"/>'
            f'<text x="42" y="{y}" class="label">{escape(label)}</text>'
            f'<text x="205" y="{y}" class="value">{value}</text>'
        )

    github_mark = (
        '<g transform="translate(238,72) scale(4.7)" fill="#586e75">'
        '<path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 '
        "2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 "
        "0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-"
        ".48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
        "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-"
        "1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-"
        ".2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 "
        "2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 "
        "1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 "
        "3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 "
        "2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-"
        '8-8z"/></g>'
    )

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="340" height="200" '
        'viewBox="0 0 340 200">'
        "<style>"
        "*{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        ".title{font-size:22px;font-weight:600;fill:#586e75}"
        ".label{font-size:14px;fill:#586e75}"
        ".value{font-size:14px;font-weight:600;fill:#586e75;text-anchor:end}"
        "</style>"
        '<rect x="1" y="1" width="338" height="198" rx="6" fill="#fff" '
        'stroke="#e4e2e2"/>'
        '<text x="30" y="40" class="title">GitHub Snapshot</text>'
        f"{''.join(rows)}{github_mark}</svg>\n"
    )


def write_atomically(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(content)
        os.replace(temporary_name, output)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("profile-summary-card-output/default/3-stats.svg"),
    )
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    profile = api_get(f"/users/{args.username}", token)
    if not isinstance(profile, dict):
        raise RuntimeError("GitHub returned an unexpected profile response")

    repositories = owned_repositories(args.username, token)
    pull_request_count, pull_requests = authored_items(args.username, "pr", token)
    issue_count, _ = authored_items(args.username, "issue", token)
    contributed_repositories = {
        item.get("repository_url")
        for item in pull_requests
        if isinstance(item.get("repository_url"), str)
    }

    metrics = [
        (
            "Total Stars",
            sum(
                int(repository.get("stargazers_count", 0))
                for repository in repositories
            ),
        ),
        ("Public Repositories", int(profile.get("public_repos", 0))),
        ("Public Pull Requests", pull_request_count),
        ("Public Issues", issue_count),
        ("Repos Contributed To", len(contributed_repositories)),
    ]
    svg = render_svg(metrics)
    if "<svg" not in svg or "</svg>" not in svg or "ERROR" in svg:
        raise RuntimeError("Generated SVG failed validation")
    write_atomically(args.output, svg)
    print(f"Generated {args.output} with {len(metrics)} public metrics")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
