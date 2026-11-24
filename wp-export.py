#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WordPress 文章导出器 —— 把主站文章导出为带 canonical 的 Markdown 内容仓。

零依赖：仅使用 Python 标准库（>=3.7）。
若环境中已安装 markdownify，会自动优先使用它以获得更高的转换质量：
    pip install markdownify

用法：
    python wp-export.py --site https://example.com --out ./content-repo
    python wp-export.py --site https://example.com --out ./content-repo --max-posts 5   # 先小批量试跑

产出结构：
    content-repo/
      articles/2026/11/<slug>.md   按年月归档的文章（含 frontmatter + canonical）
      data/posts.json               结构化索引（供 AI / 工具消费）
      README.md                     自动生成的文章索引
      .gitignore
"""

import argparse
from urllib.parse import unquote
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

USER_AGENT = "wp-export/1.0 (+content pipeline)"


# ---------------------------------------------------------------- HTML 转 Markdown

class _FallbackMarkdown(HTMLParser):
    """标准库兜底转换器：覆盖文章常见的标题/段落/列表/链接/加粗/代码/表格/图片。"""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "iframe", "form", "button"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []          # 每项: (kind, payload)
        self.skip_depth = 0
        self.in_pre = False
        self.pre_lang = ""
        self.pre_fence_written = False
        self.pre_buf = []
        self.li_stack = []
        self.table_rows = []
        self.table_row = []
        self.table_cell = []
        self.in_cell = False

    def _emit(self, text):
        self.parts.append(text)

    def _newline(self, count=2):
        s = "".join(self.parts)
        stripped = s.rstrip(" \t\n")
        if not stripped:
            return
        self.parts = [stripped]
        if not stripped.endswith("\n" * count):
            self._emit("\n" * count)

    @staticmethod
    def _lang_from_class(raw):
        for cls in (raw or "").split():
            m = re.match(r"(?:language-|lang-)([\w+#-]+)", cls)
            if m:
                return m.group(1)
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return

        if tag == "pre":
            self._newline()
            self.in_pre = True
            self.pre_lang = self._lang_from_class(a.get("class")) or ""
            self.pre_fence_written = False
            self.pre_buf = []
            return
        if self.in_pre:
            if tag == "code" and not self.pre_lang:
                self.pre_lang = self._lang_from_class(a.get("class")) or ""
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline()
            self.stack.append(("h", "#" * int(tag[1]) + " "))
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "p":
            self._newline()
        elif tag == "br":
            self._emit("  \n")
        elif tag == "hr":
            self._newline()
            self._emit("---\n\n")
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            self._emit("[")
            self.stack.append(("a", a.get("href", "")))
        elif tag == "img":
            alt = re.sub(r"[\]\[]", "", a.get("alt", "") or "")
            self._emit("![" + alt + "](" + (a.get("src") or "") + ")")
        elif tag in ("ul", "ol"):
            self._newline()
            self.li_stack.append({"type": tag, "idx": 0})
        elif tag == "li":
            self._newline(1)
            if self.li_stack:
                cur = self.li_stack[-1]
                cur["idx"] += 1
                mark = "- " if cur["type"] == "ul" else str(cur["idx"]) + ". "
            else:
                mark = "- "
            self._emit(mark)
        elif tag == "blockquote":
            self._newline()
            self.stack.append(("quote", None))
        elif tag == "code":
            self._emit("`")
        elif tag == "table":
            self._newline()
            self.table_rows = []
        elif tag == "tr":
            self.table_row = []
        elif tag in ("th", "td"):
            self.in_cell = True
            self.table_cell = []

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return

        if tag == "pre":
            if not self.pre_fence_written:
                self._emit("```" + self.pre_lang + "\n")
            code = "".join(self.pre_buf).strip("\n")
            self._emit(code)
            self._emit("\n```\n\n")
            self.in_pre = False
            return
        if self.in_pre:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "blockquote"):
            if self.stack:
                self.stack.pop()
            self._newline()
        elif tag == "p":
            self._newline()
        elif tag in ("strong", "b"):
            self._emit("**")
        elif tag in ("em", "i"):
            self._emit("*")
        elif tag == "a":
            if self.stack and self.stack[-1][0] == "a":
                href = self.stack.pop()[1]
                self._emit("](" + href + ")")
        elif tag in ("ul", "ol"):
            self._newline()
            if self.li_stack:
                self.li_stack.pop()
        elif tag == "li":
            self._emit("\n")
        elif tag == "code":
            self._emit("`")
        elif tag in ("th", "td"):
            self.table_row.append(re.sub(r"\s+", " ", "".join(self.table_cell)).strip())
            self.in_cell = False
        elif tag == "tr":
            if self.table_row:
                self.table_rows.append(self.table_row)
        elif tag == "table":
            if self.table_rows:
                width = max(len(r) for r in self.table_rows)
                rows = [r + [""] * (width - len(r)) for r in self.table_rows]
                self._emit("| " + " | ".join(rows[0]) + " |\n")
                self._emit("| " + " | ".join(["---"] * width) + " |\n")
                for r in rows[1:]:
                    self._emit("| " + " | ".join(r) + " |\n")
                self._newline()

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.in_pre:
            if not self.pre_fence_written:
                self._emit("```" + self.pre_lang + "\n")
                self.pre_fence_written = True
            self.pre_buf.append(data)
            return
        if self.in_cell:
            self.table_cell.append(data)
            return
        text = data
        if self.stack and self.stack[-1][0] == "quote":
            text = "\n".join("> " + line if line.strip() else "" for line in text.split("\n"))
        self._emit(text)

    def result(self):
        s = "".join(self.parts)
        s = re.sub(r"[ \t]+\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip() + "\n"


def html_to_markdown(raw_html):
    if not raw_html:
        return ""
    try:
        from markdownify import markdownify as md  # type: ignore
        return md(raw_html, heading_style="ATX", bullets="-").strip() + "\n"
    except ImportError:
        pass
    raw_html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", "", raw_html)
    conv = _FallbackMarkdown()
    conv.feed(raw_html)
    return conv.result()


# ---------------------------------------------------------------- 工具函数

def api_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s %s" % (e.code, url)) from e
    except urllib.error.URLError as e:
        raise RuntimeError("网络错误 %s (%s)" % (e.reason, url)) from e


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def yaml_quote(text):
    return json.dumps(text or "", ensure_ascii=False)


def slugify(title, fallback="post"):
    # 先做 URL 解码：WordPress 中文 slug 常是 %e4%bb%80... 形式
    s = unquote(title or "")
    s = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", s, flags=re.UNICODE)
    s = re.sub(r"-{2,}", "-", s).strip("-").lower()
    return s[:80] or fallback


def fetch_taxonomy(base, name):
    out = {}
    page = 1
    while True:
        url = "%s/wp-json/wp/v2/%s?per_page=100&page=%d&_fields=id,name,slug" % (base, name, page)
        try:
            items, headers = api_get(url)
        except RuntimeError:
            break
        if not isinstance(items, list) or not items:
            break
        for it in items:
            out[it["id"]] = it
        if page >= int(headers.get("X-WP-TotalPages", 1)):
            break
        page += 1
    return out


def fetch_posts(base, per_page, max_posts):
    posts = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        url = (
            "%s/wp-json/wp/v2/posts?per_page=%d&page=%d&_fields=id,date,link,slug,title,content,excerpt,categories,tags,status"
            % (base, per_page, page)
        )
        items, headers = api_get(url)
        if not isinstance(items, list):
            raise RuntimeError("REST API 返回格式异常：" + url)
        total_pages = int(headers.get("X-WP-TotalPages", page))
        posts.extend(items)
        print("  拉取第 %d/%d 页，累计 %d 篇" % (page, total_pages, len(posts)))
        if max_posts and len(posts) >= max_posts:
            posts = posts[:max_posts]
            break
        page += 1
    return posts


def render_markdown(post, cats, tags, base):
    title = strip_html(post.get("title", {}).get("rendered", "")) or "无标题"
    date_full = post.get("date", "") or ""
    date = date_full[:10] or "1970-01-01"
    link = post.get("link", "") or (base + "/?p=" + str(post.get("id")))
    excerpt = strip_html(post.get("excerpt", {}).get("rendered", ""))
    desc = (excerpt or title)[:200]
    body = html_to_markdown(post.get("content", {}).get("rendered", ""))

    tag_names = []
    for tid in post.get("tags", []) or []:
        if tid in tags:
            tag_names.append(tags[tid]["name"])
    for cid in post.get("categories", []) or []:
        if cid in cats:
            tag_names.append(cats[cid]["name"])
    tag_names = list(dict.fromkeys(tag_names))[:8]
    tag_line = ", ".join(tag_names)

    fm = (
        "---\n"
        "title: %s\n"
        "description: %s\n"
        "date: %s\n"
        "tags: [%s]\n"
        "canonical: %s\n"
        "---\n\n"
        % (yaml_quote(title), yaml_quote(desc), date, tag_line, link)
    )
    return fm + body + "\n", {"title": title, "date": date, "link": link, "tags": tag_names, "slug": post.get("slug") or slugify(title)}


def main():
    ap = argparse.ArgumentParser(description="WordPress -> Markdown 内容仓导出器")
    ap.add_argument("--site", required=True, help="主站根地址，如 https://example.com")
    ap.add_argument("--out", required=True, help="输出目录（内容仓根目录）")
    ap.add_argument("--per-page", type=int, default=100, help="每页拉取条数，最大 100")
    ap.add_argument("--max-posts", type=int, default=0, help="最多导出篇数，0 表示全部；试跑时填 5")
    args = ap.parse_args()

    base = args.site.rstrip("/")
    if not base.startswith(("http://", "https://")):
        print("错误：--site 必须以 http:// 或 https:// 开头", file=sys.stderr)
        sys.exit(2)

    print("0/4 检查 REST API ...")
    try:
        api_get(base + "/wp-json/")
    except RuntimeError as e:
        print("错误：无法访问 REST API：%s" % e, file=sys.stderr)
        print("请确认：1) 站点可公网访问 2) 设置->固定链接 已非朴素结构 3) REST API 未被插件禁用", file=sys.stderr)
        sys.exit(2)
    print("  REST API 可用")

    print("1/4 读取分类与标签 ...")
    cats = fetch_taxonomy(base, "categories")
    tags = fetch_taxonomy(base, "tags")
    print("  分类 %d 个，标签 %d 个" % (len(cats), len(tags)))

    print("2/4 拉取文章 ...")
    posts = fetch_posts(base, min(args.per_page, 100), args.max_posts)
    if not posts:
        print("没有拉到文章，请检查站点是否有已发布内容。", file=sys.stderr)
        sys.exit(2)

    print("3/4 生成 Markdown 与索引 ...")
    out = os.path.abspath(args.out)
    index = []
    for p in posts:
        md_text, meta = render_markdown(p, cats, tags, base)
        y, m = (meta["date"].split("-") + ["", ""])[:2]
        # slug 可能是 URL 编码的中文，解码后再清理成可读文件名
        fname = slugify(unquote(meta["slug"] or ""), fallback=slugify(meta["title"]))
        rel = os.path.join("articles", y, m, fname + ".md")
        path = os.path.join(out, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(md_text)
        index.append({"path": rel.replace("\\", "/"), **meta})

    data_dir = os.path.join(out, "data")
    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "posts.json"), "w", encoding="utf-8") as f:
        json.dump({"source": base, "count": len(index), "posts": index}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(out, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("__pycache__/\n*.pyc\n.DS_Store\n")

    lines = [
        "# 内容索引",
        "",
        "本站原文首发于 %s；本仓库为结构化分发副本，每篇均标注 canonical 指向原文。" % base,
        "",
        "共 %d 篇。" % len(index),
        "",
        "| 日期 | 标题 | 原文 |",
        "|---|---|---|",
    ]
    for it in sorted(index, key=lambda x: x["date"], reverse=True):
        t = it["title"].replace("|", "\\|")
        lines.append("| %s | [%s](%s) | [链接](%s) |" % (it["date"], t, it["path"], it["link"]))
    lines += [
        "",
        "## 仓库文件说明",
        "",
        "| 文件 | 用途 |",
        "|---|---|",
        "| `articles/` | 文章 Markdown 正文，每篇 frontmatter 含 canonical 指向主站原文 |",
        "| `data/posts.json` | 结构化索引，供程序化读取 |",
        "| `llms.txt` | AI/LLM 引用说明，告诉搜索引擎与 AI 引擎如何引用本站内容 |",
        "| `wp-export.py` | 导出脚本，从 WordPress REST API 拉取文章生成 Markdown，每日自动运行 |",
        "| `.github/workflows/sync.yml` | GitHub Actions 配置，每天自动同步主站新文章 |",
        "| `LICENSE` | CC0 1.0，内容可自由引用 |",
        "",
        "> 本仓库为内容分发副本，原文以主站为准。",
    ]
    with open(os.path.join(out, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("4/4 完成")
    print("  导出 %d 篇 -> %s" % (len(index), out))
    print("  索引: %s" % os.path.join(data_dir, "posts.json"))
    print("  提示：先用 --max-posts 5 试跑并检查 Markdown 质量，再全量导出。")


if __name__ == "__main__":
    main()
