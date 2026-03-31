#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Scrape article links for a target WeChat Official Account via mp.weixin.qq.com.

This script follows the approach described in the Bilibili article:
"如何使用python脚本爬取微信公众号文章？" (cv31427597)

You must provide three values copied from your logged-in WeChat Official Account
admin session:
1. cookie
2. token
3. fakeid

快速开始：
python wechat_article_links_scraper.py --summarize --summary-markdown my_summary.md --summary-provider qwen
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, List
from urllib import error, request

import requests


APPMSG_API = "https://mp.weixin.qq.com/cgi-bin/appmsg"
APPMSG_PUBLISH_API = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish"

# Local defaults for this workspace. CLI arguments still take precedence.
DEFAULT_COOKIE = (
    "请使用自己的Cookie"
)
DEFAULT_TOKEN = "请使用自己的Token"
DEFAULT_FAKEID = "请使用自己的FakeID"
DEFAULT_FINGERPRINT = "请使用自己的Fingerprint"
DEFAULT_RAW_RESPONSE_PATH = "wechat_raw_response.json"
DEFAULT_ACCOUNTS_PATH = "wechat_accounts.json"
DEFAULT_SUMMARY_OUTPUT_PATH = "wechat_ai_summary.json"
DEFAULT_SUMMARY_MARKDOWN_PATH = "wechat_ai_summary.md"
DEFAULT_ARTICLE_TIMEOUT = 20
DEFAULT_AI_CONFIG_PATH = "ai_config.json"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_MAX_REQUESTS_PER_ACCOUNT = 5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]


@dataclass
class ArticleItem:
    fakeid: str
    account_name: str
    title: str
    link: str
    create_time: str
    create_timestamp: int
    update_time: str | None = None
    digest: str | None = None
    cover: str | None = None


@dataclass
class ArticleSummary:
    account_name: str
    fakeid: str
    title: str
    link: str
    create_time: str
    content_preview: str
    summary_zh: str


class WeChatArticleScraper:
    def __init__(
        self,
        cookie: str,
        token: str,
        fakeid: str,
        api_mode: str = "publish",
        page_size: int = 5,
        request_timeout: int = 20,
        fingerprint: str | None = None,
        type_value: str = "101_1",
        free_publish_type: str = "1",
        account_name: str | None = None,
    ) -> None:
        self.cookie = cookie
        self.token = token
        self.fakeid = fakeid
        self.api_mode = api_mode
        self.page_size = page_size
        self.session = requests.Session()
        self.session.trust_env = False
        self.request_timeout = request_timeout
        self.fingerprint = fingerprint
        self.type_value = type_value
        self.free_publish_type = free_publish_type
        self.account_name = account_name or fakeid

    def _headers(self) -> dict[str, str]:
        return {
            "Cookie": self.cookie,
            "Referer": "https://mp.weixin.qq.com/",
            "User-Agent": random.choice(USER_AGENTS),
        }

    def _params(self, begin: int) -> dict[str, str]:
        if self.api_mode == "publish":
            params = {
                "sub": "list",
                "search_field": "null",
                "begin": str(begin),
                "count": str(self.page_size),
                "query": "",
                "fakeid": self.fakeid,
                "type": self.type_value,
                "free_publish_type": self.free_publish_type,
                "sub_action": "list_ex",
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            }
            if self.fingerprint:
                params["fingerprint"] = self.fingerprint
            return params

        return {
            "action": "list_ex",
            "begin": str(begin),
            "count": str(self.page_size),
            "fakeid": self.fakeid,
            "f": "json",
            "ajax": "1",
            "lang": "zh_CN",
            "query": "",
            "token": self.token,
            "type": "9",
        }

    def _request_page(self, begin: int) -> dict:
        url = APPMSG_PUBLISH_API if self.api_mode == "publish" else APPMSG_API
        response = self.session.get(
            url,
            headers=self._headers(),
            params=self._params(begin),
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("base_resp", {}).get("ret") not in (0, None):
            raise RuntimeError(
                f"WeChat API returned error: {payload.get('base_resp')}"
            )

        return payload

    @staticmethod
    def _format_ts(value: int | None) -> str | None:
        if not value:
            return None
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _normalize_link(link: str) -> str:
        if link.startswith("//"):
            return f"https:{link}"
        return link

    def fetch_all(self, delay_min: float = 1.5, delay_max: float = 3.0) -> List[ArticleItem]:
        first_page = self._request_page(0)
        total = self._extract_total(first_page)
        items = self._extract_items(first_page)

        print(f"Detected {total} articles.")

        for begin in range(self.page_size, total, self.page_size):
            sleep_seconds = random.uniform(delay_min, delay_max)
            print(f"Sleeping {sleep_seconds:.2f}s before next request...")
            time.sleep(sleep_seconds)

            page = self._request_page(begin)
            page_items = self._extract_items(page)
            items.extend(page_items)
            print(f"Fetched offset={begin}, got {len(page_items)} items.")

        return items

    def _extract_total(self, payload: dict) -> int:
        direct_total = (
            payload.get("app_msg_cnt", 0)
            or payload.get("total_count", 0)
            or payload.get("publish_page_total_count", 0)
        )
        if direct_total:
            return int(direct_total)

        publish_page = self._load_json_if_needed(payload.get("publish_page") or {})
        if isinstance(publish_page, dict):
            nested_total = (
                publish_page.get("total_count", 0)
                or publish_page.get("publish_count", 0)
            )
            if nested_total:
                return int(nested_total)

        return 0

    @staticmethod
    def _load_json_if_needed(value: Any) -> Any:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value

    def _extract_items(self, payload: dict) -> List[ArticleItem]:
        result: List[ArticleItem] = []
        raw_items = payload.get("app_msg_list", [])
        if not raw_items and "publish_page" in payload:
            publish_page = self._load_json_if_needed(payload.get("publish_page") or {})
            if isinstance(publish_page, dict):
                raw_items = publish_page.get("publish_list", [])

        raw_items = self._load_json_if_needed(raw_items)
        if not isinstance(raw_items, list):
            return result

        for item in raw_items:
            item = self._load_json_if_needed(item)
            if not isinstance(item, dict):
                continue

            if "publish_info" in item:
                publish_info = self._load_json_if_needed(item.get("publish_info") or {})
                if not isinstance(publish_info, dict):
                    continue
                nested = self._load_json_if_needed(publish_info)
                if not isinstance(nested, dict):
                    continue
                appmsgex = nested.get("appmsgex", [])
                appmsgex = self._load_json_if_needed(appmsgex)
                if not isinstance(appmsgex, list):
                    continue
                for sub_item in appmsgex:
                    sub_item = self._load_json_if_needed(sub_item)
                    if not isinstance(sub_item, dict):
                        continue
                    result.append(
                        ArticleItem(
                            fakeid=self.fakeid,
                            account_name=self.account_name,
                            title=sub_item.get("title", "").strip(),
                            link=self._normalize_link(sub_item.get("link", "").strip()),
                            create_time=self._format_ts(sub_item.get("create_time")) or "",
                            create_timestamp=int(sub_item.get("create_time") or 0),
                            update_time=self._format_ts(sub_item.get("update_time")),
                            digest=sub_item.get("digest"),
                            cover=self._normalize_link(sub_item.get("cover", "")) if sub_item.get("cover") else None,
                        )
                    )
                continue

            result.append(
                ArticleItem(
                    fakeid=self.fakeid,
                    account_name=self.account_name,
                    title=item.get("title", "").strip(),
                    link=self._normalize_link(item.get("link", "").strip()),
                    create_time=self._format_ts(item.get("create_time")) or "",
                    create_timestamp=int(item.get("create_time") or 0),
                    update_time=self._format_ts(item.get("update_time")),
                    digest=item.get("digest"),
                    cover=self._normalize_link(item.get("cover", "")) if item.get("cover") else None,
                )
            )
        return result


def save_csv(path: Path, items: List[ArticleItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "fakeid",
                "account_name",
                "title",
                "link",
                "create_time",
                "create_timestamp",
                "update_time",
                "digest",
                "cover",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def save_json(path: Path, items: List[ArticleItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump([asdict(item) for item in items], file, ensure_ascii=False, indent=2)


def save_raw_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(content)


def parse_fakeids(raw_values: List[str]) -> List[str]:
    fakeids: List[str] = []
    for raw in raw_values:
        for part in raw.split(","):
            value = part.strip()
            if value and value not in fakeids:
                fakeids.append(value)
    return fakeids


def load_accounts(path: Path) -> List[dict[str, str]]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    accounts: List[dict[str, str]] = []
    if isinstance(payload, list):
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"account #{index} must be an object")

            fakeid = str(item.get("fakeid", "")).strip()
            if not fakeid:
                raise ValueError(f"account #{index} is missing fakeid")

            accounts.append(
                {
                    "name": str(item.get("name", fakeid)).strip() or fakeid,
                    "fakeid": fakeid,
                    "token": str(item.get("token", "")).strip() or DEFAULT_TOKEN,
                    "fingerprint": str(item.get("fingerprint", "")).strip() or DEFAULT_FINGERPRINT,
                }
            )
        return accounts

    if not isinstance(payload, dict):
        raise ValueError("accounts json must be a list or object")

    shared_cookie = str(payload.get("cookie", "")).strip() or DEFAULT_COOKIE
    shared_token = str(payload.get("token", "")).strip() or DEFAULT_TOKEN
    shared_fingerprint = str(payload.get("fingerprint", "")).strip() or DEFAULT_FINGERPRINT
    raw_accounts = payload.get("accounts")
    if not isinstance(raw_accounts, list):
        raise ValueError("accounts json object must contain an accounts array")

    for index, item in enumerate(raw_accounts, start=1):
        if isinstance(item, str):
            fakeid = item.strip()
            name = fakeid
        elif isinstance(item, dict):
            fakeid = str(item.get("fakeid", "")).strip()
            name = str(item.get("name", fakeid)).strip() or fakeid
        else:
            raise ValueError(f"account #{index} must be a string or object")

        if not fakeid:
            raise ValueError(f"account #{index} is missing fakeid")

        accounts.append(
            {
                "name": name,
                "cookie": shared_cookie,
                "fakeid": fakeid,
                "token": shared_token,
                "fingerprint": shared_fingerprint,
            }
        )

    return accounts


def load_ai_config(path: Path, provider_override: str | None = None) -> dict[str, str]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, dict):
        raise ValueError("ai config json must be an object")

    provider = provider_override or str(payload.get("provider", "openai")).strip() or "openai"
    if provider not in ("openai", "qwen"):
        raise ValueError("provider must be 'openai' or 'qwen'")

    section = payload.get(provider, {})
    if section and not isinstance(section, dict):
        raise ValueError(f"{provider} section must be an object")

    api_key = str(payload.get("api_key", "")).strip()
    model = str(payload.get("model", "")).strip()
    if isinstance(section, dict):
        api_key = str(section.get("api_key", api_key)).strip()
        model = str(section.get("model", model)).strip()

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
    }


def parse_date_start(value: str | None) -> int | None:
    if not value:
        return None
    return int(datetime.strptime(value, "%Y-%m-%d").timestamp())


def parse_date_end(value: str | None) -> int | None:
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d")
    return int(dt.replace(hour=23, minute=59, second=59).timestamp())


def default_today_range() -> tuple[int, int]:
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return int(start.timestamp()), int(end.timestamp())


def filter_items_by_date(
    items: List[ArticleItem],
    start_ts: int | None,
    end_ts: int | None,
) -> List[ArticleItem]:
    filtered: List[ArticleItem] = []
    for item in items:
        if start_ts is not None and item.create_timestamp < start_ts:
            continue
        if end_ts is not None and item.create_timestamp > end_ts:
            continue
        filtered.append(item)
    return filtered


def page_is_older_than_start(items: List[ArticleItem], start_ts: int | None) -> bool:
    if start_ts is None or not items:
        return False
    timestamps = [item.create_timestamp for item in items if item.create_timestamp]
    if not timestamps:
        return False
    return max(timestamps) < start_ts


def fetch_article_html(url: str, timeout: int = DEFAULT_ARTICLE_TIMEOUT) -> str:
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url,
        headers={"User-Agent": random.choice(USER_AGENTS)},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def extract_article_text(page_html: str) -> str:
    match = re.search(
        r'<div[^>]+id="js_content"[^>]*>(.*?)</div>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    content = match.group(1) if match else page_html
    content = re.sub(r"<script.*?</script>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<style.*?</style>", " ", content, flags=re.IGNORECASE | re.DOTALL)
    content = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"</p\s*>", "\n", content, flags=re.IGNORECASE)
    content = re.sub(r"<[^>]+>", " ", content)
    content = html.unescape(content)
    content = re.sub(r"\r", "\n", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    return content.strip()


def clip_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def call_chat_completion(
    provider: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: int = 120,
    max_retries: int = 3,
) -> str:
    if provider == "qwen":
        endpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    elif provider == "openai":
        endpoint = "https://api.openai.com/v1/chat/completions"
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        req = request.Request(
            endpoint,
            data=json.dumps(
                {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                data = json.loads(resp.read().decode(charset))
                return data["choices"][0]["message"]["content"].strip()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 429 and attempt < max_retries:
                sleep_seconds = min(20, 2 ** attempt)
                print(f"Rate limited by {provider}, retrying in {sleep_seconds}s...")
                time.sleep(sleep_seconds)
                last_error = RuntimeError(f"LLM API error 429: {detail}")
                continue
            raise RuntimeError(f"LLM API error {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Unable to reach the {provider} API endpoint.") from exc

    assert last_error is not None
    raise last_error


def summarize_articles(
    items: List[ArticleItem],
    provider: str,
    model: str,
    api_key: str,
    article_timeout: int,
    content_char_limit: int,
) -> tuple[List[ArticleSummary], str]:
    system_prompt = (
        "你是一个中文内容编辑。请根据用户提供的微信公众号文章内容，"
        "输出准确、简洁、结构清晰的中文总结，避免编造。"
    )
    article_summaries: List[ArticleSummary] = []
    digest_parts: List[str] = []

    for index, item in enumerate(items, start=1):
        print(f"Summarizing article {index}/{len(items)}: {item.title}")
        page_html = fetch_article_html(item.link, timeout=article_timeout)
        article_text = clip_text(extract_article_text(page_html), content_char_limit)
        summary_zh = call_chat_completion(
            provider=provider,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_prompt=(
                f"请用中文总结下面这篇微信公众号文章。\n\n"
                f"标题：{item.title}\n"
                f"账号：{item.account_name}\n"
                f"发布时间：{item.create_time}\n"
                f"链接：{item.link}\n\n"
                f"正文：\n{article_text}\n\n"
                "请输出：\n"
                "1. 一段 80-150 字摘要\n"
                "2. 3 个要点\n"
                "3. 这篇文章适合什么人看"
            ),
        )
        article_summaries.append(
            ArticleSummary(
                account_name=item.account_name,
                fakeid=item.fakeid,
                title=item.title,
                link=item.link,
                create_time=item.create_time,
                content_preview=clip_text(article_text, 400),
                summary_zh=summary_zh,
            )
        )
        digest_parts.append(
            f"标题：{item.title}\n账号：{item.account_name}\n摘要：{summary_zh}"
        )

    overall_summary = call_chat_completion(
        provider=provider,
        api_key=api_key,
        model=model,
        system_prompt=system_prompt,
        user_prompt=(
            "请基于下面多篇微信公众号文章摘要，输出一份中文汇总。\n\n"
            + "\n\n".join(digest_parts)
            + "\n\n请输出：\n"
            "1. 今日重点主题\n"
            "2. 5 条以内核心结论\n"
            "3. 读者下一步建议"
        ),
    )
    return article_summaries, overall_summary


def resolve_output_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return base_dir / path


def build_summary_markdown(
    article_summaries: List[ArticleSummary],
    overall_summary: str,
    provider: str,
    model: str,
) -> str:
    lines = [
        "# 微信公众号文章 AI 总结",
        "",
        f"- Provider: `{provider}`",
        f"- Model: `{model}`",
        f"- Article Count: `{len(article_summaries)}`",
        "",
        "## 总结",
        "",
        overall_summary,
        "",
        "## 单篇摘要",
        "",
    ]
    for index, item in enumerate(article_summaries, start=1):
        lines.extend(
            [
                f"### {index}. {item.title}",
                "",
                f"- 账号：{item.account_name}",
                f"- fakeid：`{item.fakeid}`",
                f"- 发布时间：{item.create_time}",
                f"- 链接：{item.link}",
                "",
                item.summary_zh,
                "",
            ]
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape WeChat Official Account article links with cookie/token/fakeid."
    )
    parser.add_argument(
        "--cookie",
        default=DEFAULT_COOKIE,
        help="Cookie copied from mp.weixin.qq.com request headers",
    )
    parser.add_argument(
        "--token",
        default=DEFAULT_TOKEN,
        help="Token copied from mp.weixin.qq.com request payload",
    )
    parser.add_argument(
        "--fakeid",
        action="append",
        help="Fakeid copied from mp.weixin.qq.com request payload; repeat or comma-separate for multiple accounts",
    )
    parser.add_argument(
        "--api-mode",
        choices=["publish", "legacy"],
        default="publish",
        help="Use the newer appmsgpublish endpoint or the older appmsg endpoint",
    )
    parser.add_argument(
        "--fingerprint",
        default=DEFAULT_FINGERPRINT,
        help="Fingerprint copied from appmsgpublish request payload",
    )
    parser.add_argument(
        "--accounts-json",
        default=DEFAULT_ACCOUNTS_PATH,
        help="JSON file containing one or more account configs",
    )
    parser.add_argument("--summarize", action="store_true", help="Fetch article content and summarize in Chinese")
    parser.add_argument(
        "--summary-provider",
        choices=["qwen", "openai"],
        default=None,
        help="LLM provider used for summarization",
    )
    parser.add_argument("--summary-model", default=None, help="LLM model name used for summarization")
    parser.add_argument(
        "--ai-config",
        default=DEFAULT_AI_CONFIG_PATH,
        help="AI config JSON path",
    )
    parser.add_argument(
        "--summary-output",
        default=DEFAULT_SUMMARY_OUTPUT_PATH,
        help="Summary JSON output path",
    )
    parser.add_argument(
        "--summary-markdown",
        default=DEFAULT_SUMMARY_MARKDOWN_PATH,
        help="Summary Markdown output path",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="Base output directory for generated files",
    )
    parser.add_argument(
        "--article-timeout",
        type=int,
        default=DEFAULT_ARTICLE_TIMEOUT,
        help="Timeout for fetching public article pages",
    )
    parser.add_argument(
        "--content-char-limit",
        type=int,
        default=6000,
        help="Maximum article characters sent to the model",
    )
    parser.add_argument("--type-value", default="101_1", help="Request type parameter, e.g. 101_1 or 9")
    parser.add_argument("--free-publish-type", default="1", help="free_publish_type for appmsgpublish mode")
    parser.add_argument("--page-size", type=int, default=5, help="Items fetched per request")
    parser.add_argument("--csv", default="wechat_articles.csv", help="CSV output path")
    parser.add_argument("--json", default="wechat_articles.json", help="JSON output path")
    parser.add_argument(
        "--raw-json",
        default=DEFAULT_RAW_RESPONSE_PATH,
        help="Raw first-page API response output path for debugging",
    )
    parser.add_argument("--start-date", help="Filter articles from this date, format YYYY-MM-DD")
    parser.add_argument("--end-date", help="Filter articles until this date, format YYYY-MM-DD")
    parser.add_argument("--delay-min", type=float, default=1.5, help="Minimum sleep between requests")
    parser.add_argument("--delay-max", type=float, default=3.0, help="Maximum sleep between requests")
    parser.add_argument(
        "--max-requests-per-account",
        type=int,
        default=DEFAULT_MAX_REQUESTS_PER_ACCOUNT,
        help="Maximum list API requests per account; set 0 for no limit",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.delay_min < 0 or args.delay_max < 0 or args.delay_min > args.delay_max:
        print("Invalid delay range.", file=sys.stderr)
        return 2
    if args.max_requests_per_account < 0:
        print("max-requests-per-account cannot be negative.", file=sys.stderr)
        return 2

    try:
        if args.start_date or args.end_date:
            start_ts = parse_date_start(args.start_date)
            end_ts = parse_date_end(args.end_date)
        else:
            start_ts, end_ts = default_today_range()
    except ValueError:
        print("Invalid date format. Use YYYY-MM-DD.", file=sys.stderr)
        return 2

    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        print("start-date cannot be later than end-date.", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir)

    model = ""
    api_key = ""
    if args.summarize:
        provider = args.summary_provider
        ai_config_path = Path(args.ai_config)
        if ai_config_path.exists():
            try:
                ai_config = load_ai_config(ai_config_path, provider_override=provider)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"Failed to read ai config: {exc}", file=sys.stderr)
                return 2
            if provider is None:
                provider = ai_config["provider"] or "openai"
            api_key = ai_config["api_key"]
            if ai_config["model"]:
                model = ai_config["model"]

        if provider is None:
            provider = "openai"

        if provider == "qwen":
            api_key = api_key or os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY") or ""
            model = args.summary_model or model or "qwen-plus"
        else:
            api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
            model = args.summary_model or model or "gpt-4.1-mini"

        if not api_key:
            print("Missing API key for summarization.", file=sys.stderr)
            return 2
        args.summary_provider = provider

    accounts_path = Path(args.accounts_json)
    accounts: List[dict[str, str]]
    if accounts_path.exists():
        try:
            accounts = load_accounts(accounts_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Failed to read accounts json: {exc}", file=sys.stderr)
            return 2
    else:
        fakeids = parse_fakeids(args.fakeid or [DEFAULT_FAKEID])
        accounts = [
            {
                "name": fakeid,
                "cookie": args.cookie,
                "fakeid": fakeid,
                "token": args.token,
                "fingerprint": args.fingerprint,
            }
            for fakeid in fakeids
        ]

    try:
        all_items: List[ArticleItem] = []

        for index, account in enumerate(accounts):
            fakeid = account["fakeid"]
            scraper = WeChatArticleScraper(
                cookie=account.get("cookie", args.cookie),
                token=account["token"],
                fakeid=fakeid,
                api_mode=args.api_mode,
                page_size=args.page_size,
                fingerprint=account["fingerprint"],
                type_value=args.type_value,
                free_publish_type=args.free_publish_type,
                account_name=account["name"],
            )

            first_page = scraper._request_page(0)
            raw_path = resolve_output_path(output_dir, args.raw_json)
            if len(accounts) > 1:
                safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in account["name"])
                raw_path = raw_path.with_name(f"{raw_path.stem}_{index + 1}_{safe_name}{raw_path.suffix}")
            save_raw_json(raw_path, first_page)

            total = scraper._extract_total(first_page)
            items = scraper._extract_items(first_page)
            request_count = 1
            if page_is_older_than_start(items, start_ts):
                print(
                    f"First page for account={account['name']} is already older than start-date. "
                    f"Skipping further requests."
                )
                all_items.extend(items)
                continue

            print(f"Detected {total} articles for account={account['name']} fakeid={fakeid}.")

            for begin in range(scraper.page_size, total, scraper.page_size):
                if args.max_requests_per_account and request_count >= args.max_requests_per_account:
                    print(
                        f"Reached request limit for account={account['name']} "
                        f"({args.max_requests_per_account} requests)."
                    )
                    break

                sleep_seconds = random.uniform(args.delay_min, args.delay_max)
                print(f"Sleeping {sleep_seconds:.2f}s before next request...")
                time.sleep(sleep_seconds)

                page = scraper._request_page(begin)
                request_count += 1
                page_items = scraper._extract_items(page)
                items.extend(page_items)
                print(
                    f"Fetched account={account['name']}, fakeid={fakeid}, "
                    f"offset={begin}, got {len(page_items)} items. requests={request_count}"
                )
                if page_is_older_than_start(page_items, start_ts):
                    print(
                        f"Stopping early for account={account['name']} because current page is "
                        f"already older than start-date."
                    )
                    break

            all_items.extend(items)

        items = filter_items_by_date(all_items, start_ts, end_ts)
    except requests.HTTPError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        return 1
    except requests.RequestException as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1

    csv_path = resolve_output_path(output_dir, args.csv)
    json_path = resolve_output_path(output_dir, args.json)
    save_csv(csv_path, items)
    save_json(json_path, items)

    print(f"Saved {len(items)} records to {csv_path}")
    print(f"Saved {len(items)} records to {json_path}")

    if args.summarize:
        if not items:
            print("No articles matched the date filter; skipping summarization.")
            return 0

        try:
            article_summaries, overall_summary = summarize_articles(
                items=items,
                provider=args.summary_provider,
                model=model,
                api_key=api_key,
                article_timeout=args.article_timeout,
                content_char_limit=args.content_char_limit,
            )
        except requests.HTTPError as exc:
            print(f"Summary HTTP error: {exc}", file=sys.stderr)
            return 1
        except requests.RequestException as exc:
            print(f"Summary request failed: {exc}", file=sys.stderr)
            return 1

        summary_path = resolve_output_path(output_dir, args.summary_output)
        summary_markdown_path = resolve_output_path(output_dir, args.summary_markdown)
        summary_payload = {
            "provider": args.summary_provider,
            "model": model,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "article_count": len(article_summaries),
            "overall_summary_zh": overall_summary,
            "articles": [asdict(item) for item in article_summaries],
        }
        save_raw_json(summary_path, summary_payload)
        save_text(
            summary_markdown_path,
            build_summary_markdown(
                article_summaries=article_summaries,
                overall_summary=overall_summary,
                provider=args.summary_provider,
                model=model,
            ),
        )
        print(f"Saved AI summary JSON to {summary_path}")
        print(f"Saved AI summary Markdown to {summary_markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
