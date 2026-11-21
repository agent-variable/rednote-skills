#!/usr/bin/env python3
"""Read public provider pages and produce a reproducible free-allowance catalogue."""

import argparse
import gzip
import hashlib
import html
import io
import json
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "sources.json"
SNAPSHOT = ROOT / "data" / "catalog.json"
WEB_FALLBACK = ROOT / "references" / "web-fallback.md"
UTC = timezone.utc
LOCAL = timezone(timedelta(hours=8))
MAX_BYTES = 4_000_000
STALE_HOURS = 24
SCHEMA = 1

MARKETS = {"cn": "中国大陆站", "international": "国际服务"}
ACCESS = {"api": "外部 API", "product": "产品内", "platform": "指定开发平台"}
TOPICS = {
    "text": "文本", "code": "代码", "image": "图像", "video": "视频",
    "audio": "语音与音频", "documents": "文档解析", "embeddings": "向量与重排",
}
CADENCE = {
    "daily": "每天", "weekly": "每周", "monthly": "每月",
    "one-off": "一次性", "limited": "限时活动", "open": "当前免费可用",
}
STATUS = {
    "verified": "已核验", "source_unavailable": "来源不可用", "needs_review": "规则待复核",
    "expired": "已截止", "upcoming": "待开始",
}
BILLING = {
    "stops": "超额即停", "opt-in-stop": "可设置用完即停",
    "paid-overage": "超额计费", "unknown": "超额规则待确认",
}
IGNORED = {"script", "style", "template", "noscript", "svg", "head"}
BLOCKS = {"br", "p", "div", "li", "td", "th", "tr", "section", "article",
          "h1", "h2", "h3", "h4", "h5", "h6"}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = []

    def handle_starttag(self, tag, attrs):
        if tag in IGNORED:
            self.ignored.append(tag)
        elif tag in BLOCKS and not self.ignored:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag == self.ignored[-1]:
                self.ignored.pop()
        elif tag in BLOCKS:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCKS and not self.ignored:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def page_text(text, content_type):
    if content_type in {"text/plain", "text/markdown"}:
        return normalize(text)
    if content_type != "text/html":
        raise ValueError(f"unsupported content type {content_type}")
    parser = VisibleText()
    parser.feed(text)
    parser.close()
    return normalize("".join(parser.parts))


def https_host(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443)):
        raise ValueError(f"expected an HTTPS URL on port 443: {url!r}")
    return parsed.hostname


class SourceRedirect(HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if https_host(newurl) != self.host:
            raise ValueError("redirect to a different host")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def read_page(page):
    url = page["url"]
    host = https_host(url)
    try:
        # Use an isolated opener without a cookie store, authorization or provider accounts.
        opener = build_opener(SourceRedirect(host))
        request = Request(url, headers={
            "User-Agent": "free-ai-token-finder/3.0 (public pricing catalogue)",
            "Accept": "text/html, text/markdown, text/plain",
            "Accept-Encoding": "gzip, identity",
        })
        with opener.open(request, timeout=9) as response:
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("response exceeds size limit")
            if (response.headers.get("Content-Encoding", "").lower() == "gzip"
                    or raw.startswith(b"\x1f\x8b")):
                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as compressed:
                    raw = compressed.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES:
                    raise ValueError("decompressed response exceeds size limit")
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            text = page_text(raw.decode(charset), content_type)
            if not text:
                raise ValueError("no visible page text")
            return {
                "text": text,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
    except HTTPError as error:
        error.close()
        return {"error": f"HTTP {error.code}"}
    except (URLError, OSError, ValueError, LookupError, EOFError, HTTPException) as error:
        return {"error": str(error)}


def parse_datetime(text):
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError(f"timezone required: {text!r}")
    return value


def load_registry(path):
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry["schema_version"] != SCHEMA:
        raise ValueError("unsupported source registry schema")
    pages = registry["pages"]
    for page in pages.values():
        https_host(page["url"])
    ids = set()
    for offer in registry["offers"]:
        if offer["id"] in ids:
            raise ValueError(f"duplicate offer {offer['id']}")
        ids.add(offer["id"])
        if (offer["market"] not in MARKETS or offer["access"] not in ACCESS
                or offer["cadence"] not in CADENCE or not offer["topics"]
                or not set(offer["topics"]) <= TOPICS.keys() or not offer["checks"]
                or offer["billing"] not in BILLING
                or offer["no_upfront_payment"] not in (True, False, None)):
            raise ValueError(f"invalid offer classification: {offer['id']}")
        for field in ("starts_at", "ends_at"):
            if field in offer:
                parse_datetime(offer[field])
        for check in offer["checks"]:
            if check["page"] not in pages:
                raise ValueError(f"unknown page in {offer['id']}: {check['page']}")
            pattern = re.compile(check["pattern"], re.IGNORECASE)
            if "capture" in check and "value" not in pattern.groupindex:
                raise ValueError(f"capture requires a named value group in {offer['id']}")
    return registry


def verify_offer(offer, pages, observations, now):
    urls = list(dict.fromkeys(pages[check["page"]]["url"] for check in offer["checks"]))
    common = ("id", "title", "provider", "market", "access", "cadence", "topics")
    result = {key: offer[key] for key in common}
    result["source_urls"] = urls
    if "ends_at" in offer and now >= parse_datetime(offer["ends_at"]):
        return dict(result, status="expired", ends_at=offer["ends_at"])
    if "starts_at" in offer and now < parse_datetime(offer["starts_at"]):
        return dict(result, status="upcoming", starts_at=offer["starts_at"])
    missing = sorted({check["page"] for check in offer["checks"]
                      if "error" in observations[check["page"]]})
    review_note = offer.get("review_note")
    if missing:
        result.update(status="source_unavailable", unavailable_pages=missing)
        if review_note:
            result["review_note"] = review_note
        return result
    if review_note:
        return dict(result, status="needs_review", review_note=review_note)

    captures = {}
    failed = []
    for check in offer["checks"]:
        text = observations[check["page"]]["text"]
        matches = list(re.finditer(check["pattern"], text, re.IGNORECASE))
        if not matches:
            failed.append(check["label"])
        elif "capture" in check:
            values = {normalize(match["value"]) for match in matches}
            if len(values) != 1:
                failed.append(check["label"] + "（值不唯一）")
            else:
                field = check["capture"]
                value = values.pop()
                if field in captures and captures[field] != value:
                    failed.append(check["label"] + "（与其他官方字段不一致）")
                else:
                    captures[field] = value
    if failed:
        return dict(result, status="needs_review", failed_checks=failed)

    for field in ("amount", "eligibility", "timing", "billing_note"):
        result[field] = offer[field].format_map(captures)
    for field in ("billing", "no_upfront_payment", "starts_at", "ends_at"):
        if field in offer:
            result[field] = offer[field]
    return dict(result, status="verified")


def collect(registry, workers):
    pages = registry["pages"]
    groups = {}
    for key, page in pages.items():
        groups.setdefault(https_host(page["url"]), []).append((key, page))

    def read_host(group):
        return [(key, read_page(page)) for key, page in group]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        observations = dict(pair for group in pool.map(read_host, groups.values()) for pair in group)
    now = datetime.now(UTC)
    offers = [verify_offer(offer, pages, observations, now) for offer in registry["offers"]]
    sources = []
    for key, page in pages.items():
        observed = observations[key]
        source = {"id": key, "provider": page["provider"], "url": page["url"]}
        if "error" in observed:
            source.update(status="unavailable", error=observed["error"])
        else:
            source.update(status="fetched", sha256=observed["sha256"],
                          observed_at=observed["observed_at"])
        sources.append(source)
    return {"schema_version": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
            "registry_revision": registry["revision"], "sources": sources, "offers": offers}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def atomic_write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}-", delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(contents)
            handle.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def load_snapshot(path):
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if snapshot["schema_version"] != SCHEMA:
        raise ValueError("unsupported snapshot schema")
    parse_datetime(snapshot["generated_at"])
    return snapshot


def view(snapshot, now, args=None):
    active, exceptions = [], []
    for entry in snapshot["offers"]:
        offer = dict(entry)
        if args:
            if args.market and offer["market"] != args.market:
                continue
            if args.access and offer["access"] != args.access:
                continue
            if args.topic and not set(args.topic).intersection(offer["topics"]):
                continue
            if args.cadence and offer["cadence"] != args.cadence:
                continue
        if offer["status"] == "verified" and "ends_at" in offer:
            if now >= parse_datetime(offer["ends_at"]):
                keep = ("id", "title", "provider", "market", "access", "cadence",
                        "topics", "source_urls", "ends_at")
                offer = {key: offer[key] for key in keep}
                offer["status"] = "expired"
        if offer["status"] != "verified":
            exceptions.append(offer)
            continue
        if args:
            if args.billing and offer["billing"] != args.billing:
                continue
            if args.no_upfront_payment and offer.get("no_upfront_payment") is not True:
                continue
        active.append(offer)
    active.sort(key=lambda offer: (list(CADENCE).index(offer["cadence"]),
                                   offer.get("ends_at", "~"), offer["id"]))
    generated = parse_datetime(snapshot["generated_at"])
    return {
        "schema_version": SCHEMA,
        "generated_at": snapshot["generated_at"],
        "valid_until": (generated + timedelta(hours=STALE_HOURS)).isoformat(timespec="seconds"),
        "registry_revision": snapshot["registry_revision"],
        "is_stale": now >= generated + timedelta(hours=STALE_HOURS),
        "coverage": {"source_pages": len(snapshot["sources"]),
                     "readable_pages": sum(s["status"] == "fetched" for s in snapshot["sources"]),
                     "configured_offers": len(snapshot["offers"]),
                     "matching_verified_offers": len(active)},
        "offers": active,
        "exceptions": exceptions,
        "sources": snapshot["sources"],
    }


def display_time(timestamp):
    return parse_datetime(timestamp).astimezone(LOCAL).strftime("%Y-%m-%d %H:%M UTC+8")


def labels(offer):
    upfront = {True: "无需预充值", False: "存在资金门槛", None: "预充值待确认"}
    return " · ".join([
        MARKETS[offer["market"]], ACCESS[offer["access"]],
        "、".join(TOPICS[topic] for topic in offer["topics"]),
        BILLING[offer["billing"]], upfront[offer["no_upfront_payment"]],
        offer["amount"],
    ])


def markdown(data):
    counts = data["coverage"]
    status = "历史快照，今天可用性需刷新" if data["is_stale"] else "已取得官方证据"
    output = [
        "# 免费 AI 额度目录",
        "",
        f"核验时间 {display_time(data['generated_at'])}。{status}。",
        f"快照有效至 {display_time(data['valid_until'])}，超期后按历史资料查看。",
        (f"读取 {counts['readable_pages']}/{counts['source_pages']} 个来源页面。"
         f"注册 {counts['configured_offers']} 项权益，本次匹配 {counts['matching_verified_offers']} 项。"),
    ]
    for cadence, heading in CADENCE.items():
        group = [offer for offer in data["offers"] if offer["cadence"] == cadence]
        if not group:
            continue
        output.extend(["", f"## {heading}", ""])
        for offer in group:
            urls = " · ".join(f"[官方来源 {index}]({url})"
                              for index, url in enumerate(offer["source_urls"], 1))
            output.append(
                f"- **{offer['title']}**。{labels(offer)}。"
                f"{offer['eligibility']}。{offer['timing']}。{offer['billing_note']}。 {urls}"
            )
    if data["exceptions"]:
        output.extend(["", "## 待核验及已截止", ""])
        for offer in data["exceptions"]:
            details = offer.get("failed_checks", [])
            if offer.get("review_note"):
                details = [*details, offer["review_note"]]
            if offer.get("unavailable_pages") and not details:
                details = ["未读到完整官方页面"]
            reason = f"（{'、'.join(details)}）" if details else ""
            urls = " · ".join(f"[官方来源 {index}]({url})"
                              for index, url in enumerate(offer["source_urls"], 1))
            output.append(f"- {offer['title']} · {STATUS[offer['status']]}{reason}。 {urls}")
    return "\n".join(output) + "\n"


def html_page(data):
    counts = data["coverage"]
    groups = []
    for cadence, heading in CADENCE.items():
        offers = [item for item in data["offers"] if item["cadence"] == cadence]
        if not offers:
            continue
        rows = []
        for offer in offers:
            links = " · ".join(f'<a href="{html.escape(url, quote=True)}">官方来源 {index}</a>'
                               for index, url in enumerate(offer["source_urls"], 1))
            meta = labels(offer)
            detail = "。".join(offer[key] for key in ("eligibility", "timing", "billing_note"))
            rows.append(f'<article data-offer-id="{html.escape(offer["id"], quote=True)}">'
                        f"<h3>{html.escape(offer['title'])}</h3>"
                        f"<p><strong>{html.escape(meta)}</strong></p>"
                        f"<p>{html.escape(detail)}。</p><p>{links}</p></article>")
        groups.append(f"<section><h2>{heading}</h2>{''.join(rows)}</section>")
    exceptions = "".join(
        f"<li>{html.escape(entry['title'])} · {STATUS[entry['status']]}</li>"
        for entry in data["exceptions"]
    )
    timestamp = display_time(data["generated_at"])
    valid = display_time(data["valid_until"])
    return f"""<!doctype html>
<html lang="zh-Hans">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>免费 AI 额度目录</title>
<style>
  body {{ font: 1rem/1.65 system-ui,sans-serif; color:#16283b; background:#f8f3e9; max-width:54rem; margin:3rem auto; padding:0 1.25rem }}
  h1 {{ font-size:clamp(2rem,5vw,3.5rem); line-height:1.16; margin:0 }}
  h2 {{ border-bottom:1px solid #aeb7b8; padding-bottom:.35rem }}
  h3,p {{ margin:.45rem 0 }}
  section {{ margin:2rem 0 }}
  article {{ background:#fffcf6; border-left:4px solid #245043; padding:.7rem 1rem; margin:1rem 0 }}
  a {{ color:#8f2d1e; text-underline-offset:.2em }}
</style>
<main>
<h1>免费 AI 额度目录</h1>
<p>核验时间 {timestamp}，建议在 {valid} 前刷新。</p>
<p>读取 {counts['readable_pages']}/{counts['source_pages']} 个官方页面，核验 {counts['matching_verified_offers']} 项权益。</p>
<p><a href="catalog.json">JSON 数据</a> · <a href="catalog.md">Markdown 目录</a></p>
{''.join(groups)}
{f'<section><h2>待核验及已截止</h2><ul>{exceptions}</ul></section>' if exceptions else ''}
</main>
</html>
"""


def redskill_markdown(data, public_base):
    fallback = WEB_FALLBACK.read_text(encoding="utf-8").strip()
    if public_base:
        https_host(public_base)
        parsed = urlsplit(public_base)
        if parsed.query or parsed.fragment or re.search(r"[\s<>]", public_base):
            raise ValueError("public base URL must be a static HTTPS directory")
        web = public_base.rstrip("/") + "/index.html"
        endpoint = public_base.rstrip("/") + "/catalog.json"
        source = f"公开目录入口为 [网页]({web}) 和 [catalog.json]({endpoint})。可用来确定已登记来源，留意目录的核验时间和有效期。"
    else:
        source = "文末附带带日期的官方来源目录，可作为联网核验的起点或无网时的历史参考。"
    intro = f"""---
name: free-ai-token-finder
description: 在统一的官方免费 AI 额度目录中按地区站点、API、产品、用途和周期查询，查看额度、领取门槛和更新日期。
---

# 免费 AI Token 查找器

## 优先运行 Python 工具

先检查已安装的同名 Skill 目录。如果可以执行终端命令、有 Python 3.10+，且目录里有 `scripts/catalog.py` 和 `data/sources.json`，运行 `python3 scripts/catalog.py query --format json`。按需求加筛选参数，例如 `--market cn --access api --topic text --no-upfront-payment`。用户要求实时核验、快照缺失或过期时，先用 `python3 scripts/catalog.py refresh`。脚本的空结果和来源异常也要如实报告。

{fallback}

{source}

根据读者的地区、用途、接入方式和费用条件筛选。中国大陆站与国际站分开。需要 Python 或通用 API 时只选标有外部 API 的福利。明确要求零预充值或超额即停时，保留有依据的条目。条件待确认、已截止的条目单独呈现。保留官方链接、原始单位、核验时间和例外状态。

文末快照生成于 {display_time(data['generated_at'])}。到 {display_time(data['valid_until'])} 后只作为历史参考。符合的条目为零时如实返回，并注明本次覆盖范围。查找使用公开资料，用户自行领取。

"""
    return intro + markdown(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sources", help="list the fixed source registry")
    refresh = commands.add_parser("refresh", help="read official pages and update the snapshot")
    refresh.add_argument("--workers", type=int, choices=range(1, 7), default=4)
    query = commands.add_parser("query", help="query a saved snapshot or refresh live")
    query.add_argument("--live", action="store_true")
    query.add_argument("--format", choices=("markdown", "json"), default="markdown")
    query.add_argument("--market", choices=MARKETS)
    query.add_argument("--access", choices=ACCESS)
    query.add_argument("--topic", choices=TOPICS, action="append")
    query.add_argument("--cadence", choices=CADENCE)
    query.add_argument("--billing", choices=BILLING)
    query.add_argument("--no-upfront-payment", action="store_true")
    export = commands.add_parser("export", help="generate static web files and a Markdown upload")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--public-base-url")
    args = parser.parse_args(argv)

    try:
        if args.command == "sources":
            registry = load_registry(args.registry)
            print(json_text(registry), end="")
            return 0
        if args.command == "refresh" or (args.command == "query" and args.live):
            snapshot = collect(load_registry(args.registry), getattr(args, "workers", 4))
            if args.command == "refresh":
                shown = view(snapshot, datetime.now(UTC))
                if shown["offers"]:
                    atomic_write(args.snapshot, json_text(snapshot))
                print(markdown(shown), end="")
                return 0 if shown["offers"] else 2
        else:
            snapshot = load_snapshot(args.snapshot)

        reported = view(snapshot, datetime.now(UTC), args if args.command == "query" else None)
        if args.command == "query":
            output = json_text(reported) if args.format == "json" else markdown(reported)
            print(output, end="")
            if args.live and not any(item["status"] == "verified" for item in snapshot["offers"]):
                return 2
            return 0
        if args.command == "export":
            upload = redskill_markdown(reported, args.public_base_url)
            web = args.output / "web"
            atomic_write(web / "catalog.json", json_text(reported))
            atomic_write(web / "catalog.md", markdown(reported))
            atomic_write(web / "index.html", html_page(reported))
            atomic_write(args.output / "redskill-upload" / "SKILL.md", upload)
            return 0
    except (OSError, ValueError, KeyError, re.error) as error:
        print(f"catalog: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
