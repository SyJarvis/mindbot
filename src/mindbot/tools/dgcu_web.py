"""东莞城市学院官网信息查询工具."""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from datetime import datetime
from html.parser import HTMLParser

from mindbot.capability.backends.tooling.models import Tool
from mindbot.utils import get_logger

logger = get_logger("tools.dgcu_web")

DGCU_BASE_URL = "https://www.dgcu.edu.cn"


class DGCUNewsParser(HTMLParser):
    """解析官网新闻列表页面."""

    def __init__(self) -> None:
        super().__init__()
        self.news_items: list[dict[str, str]] = []
        self._current_item: dict[str, str] = {}
        self._in_title = False
        self._in_date = False
        self._in_link = False
        self._current_link = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self._current_link = value
                    self._in_link = True
        elif tag in ("span", "p", "div"):
            for name, value in attrs:
                if name == "class" and value and "date" in value.lower():
                    self._in_date = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_link = False
            self._in_title = False
        elif tag in ("span", "p", "div"):
            self._in_date = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return

        # 检测标题（通常在链接内且有一定长度）
        if self._in_link and len(text) > 5 and not text.isdigit():
            self._current_item["title"] = text
            if self._current_link:
                self._current_item["link"] = self._current_link

        # 检测日期
        if self._in_date:
            # 匹配日期格式如 2024-01-15 或 2024.01.15
            date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", text)
            if date_match:
                self._current_item["date"] = date_match.group()

        # 如果有标题和链接，保存
        if "title" in self._current_item and "link" in self._current_item:
            self.news_items.append(self._current_item.copy())
            self._current_item = {}


class DGCUContentParser(HTMLParser):
    """解析新闻详情页面内容."""

    def __init__(self) -> None:
        super().__init__()
        self.content_parts: list[str] = []
        self._in_content = False
        self._skip_tags = {"script", "style", "nav", "header", "footer"}
        self._current_skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._current_skip = True
        elif tag in ("p", "div", "article", "section", "span"):
            for name, value in attrs:
                if name == "class" and value:
                    # 常见的内容区域class
                    content_classes = ["content", "article", "text", "body", "main", "news"]
                    if any(c in value.lower() for c in content_classes):
                        self._in_content = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._current_skip = False
        elif tag in ("p", "div", "article", "section"):
            self._in_content = False

    def handle_data(self, data: str) -> None:
        if self._current_skip:
            return
        text = data.strip()
        if text and len(text) > 10:
            self.content_parts.append(text)


def _fetch_url(url: str, timeout: int = 10) -> str:
    """获取URL内容."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml",
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return ""
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")
        return ""


def _extract_news_list(html: str, limit: int = 10) -> list[dict[str, str]]:
    """从HTML中提取新闻列表."""
    items: list[dict[str, str]] = []

    # 使用正则表达式提取新闻链接和标题
    # 匹配模式：<a href="..." ...>标题</a>
    pattern = r'<a[^>]*href=["\']([^"\']*(?:news|article|info|detail)[^"\']*)["\'][^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html, re.IGNORECASE)

    for link, title in matches:
        title = title.strip()
        if len(title) < 5 or title.isdigit():
            continue

        # 处理相对链接
        if link.startswith("/"):
            link = DGCU_BASE_URL + link
        elif not link.startswith("http"):
            link = DGCU_BASE_URL + "/" + link

        # 提取日期
        date_match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", html)
        date = date_match.group() if date_match else ""

        item = {"title": title, "link": link, "date": date}
        if item not in items:
            items.append(item)

    return items[:limit]


def _extract_content(html: str) -> str:
    """从HTML中提取正文内容."""
    # 移除script和style标签内容
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # 提取p标签内容
    paragraphs = re.findall(r"<p[^>]*>(.*?)</p>", html, re.DOTALL | re.IGNORECASE)
    texts = []
    for p in paragraphs:
        # 移除HTML标签
        text = re.sub(r"<[^>]+>", "", p)
        text = text.strip()
        if text and len(text) > 15:
            texts.append(text)

    # 如果没找到p标签，尝试提取div内容
    if not texts:
        divs = re.findall(r'<div[^>]*class=["\'][^"\']*content[^"\']*["\'][^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
        for div in divs:
            text = re.sub(r"<[^>]+>", "", div)
            text = text.strip()
            if text and len(text) > 15:
                texts.append(text)

    return "\n\n".join(texts[:10])


def fetch_dgcu_news(limit: int = 5) -> str:
    """获取东莞城市学院学校要闻列表.

    Args:
        limit: 返回新闻条数，默认5条，最多10条

    Returns:
        JSON格式的新闻列表，包含标题、链接、日期
    """
    limit = min(limit, 10)
    html = _fetch_url(f"{DGCU_BASE_URL}/news.html")

    if not html:
        return json.dumps({"error": "无法获取官网新闻页面", "news": []}, ensure_ascii=False)

    news = _extract_news_list(html, limit)

    if not news:
        # 尝试从首页获取
        html = _fetch_url(DGCU_BASE_URL)
        news = _extract_news_list(html, limit)

    return json.dumps({
        "source": "东莞城市学院官网",
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(news),
        "news": news
    }, ensure_ascii=False, indent=2)


def fetch_dgcu_article(url: str) -> str:
    """获取东莞城市学院指定新闻/文章详情.

    Args:
        url: 文章链接地址（可以是相对路径如 /news/123.html 或完整URL）

    Returns:
        JSON格式的文章内容
    """
    # 处理相对路径
    if url.startswith("/"):
        url = DGCU_BASE_URL + url
    elif not url.startswith("http"):
        url = DGCU_BASE_URL + "/" + url

    # 验证URL属于官网域名
    if not url.startswith(DGCU_BASE_URL):
        # 允许子域名
        if not re.match(r"https?://[a-z]*\.?dgcu\.edu\.cn", url):
            return json.dumps({
                "error": "URL不属于东莞城市学院官网域名",
                "url": url
            }, ensure_ascii=False)

    html = _fetch_url(url)

    if not html:
        return json.dumps({"error": "无法获取文章页面", "url": url}, ensure_ascii=False)

    content = _extract_content(html)

    # 提取标题
    title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "未知标题"
    # 清理标题中的网站名称
    title = re.sub(r"[-_|].*东莞.*学院.*", "", title).strip()

    return json.dumps({
        "source": "东莞城市学院官网",
        "url": url,
        "title": title,
        "content": content if content else "未能提取正文内容",
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False, indent=2)


def search_dgcu_page(page_type: str = "about") -> str:
    """获取东莞城市学院指定页面类型的内容.

    Args:
        page_type: 页面类型，可选值：
            - about: 学校概况
            - dan.html: 党建之窗
            - 其他具体页面路径

    Returns:
        JSON格式的页面内容
    """
    # 映射页面类型到URL
    page_map = {
        "about": "/about.html",
        "学校概况": "/about.html",
        "党建": "/dan.html",
        "党建之窗": "/dan.html",
    }

    path = page_map.get(page_type, page_type)
    if not path.startswith("/"):
        path = "/" + path

    url = DGCU_BASE_URL + path
    html = _fetch_url(url)

    if not html:
        return json.dumps({"error": f"无法获取页面: {url}", "page_type": page_type}, ensure_ascii=False)

    content = _extract_content(html)

    # 提取标题
    title_match = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else page_type

    return json.dumps({
        "source": "东莞城市学院官网",
        "page_type": page_type,
        "url": url,
        "title": title,
        "content": content if content else "未能提取页面内容",
        "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }, ensure_ascii=False, indent=2)


def create_dgcu_tools() -> list[Tool]:
    """创建东莞城市学院官网查询工具."""
    return [
        Tool(
            name="fetch_dgcu_news",
            description=(
                "获取东莞城市学院官网学校要闻列表。"
                "返回最新的学校新闻标题、链接和日期信息。"
                "当用户询问学校最新动态、新闻、要闻时使用此工具。"
            ),
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回新闻条数，默认5条，最多10条",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 10,
                    }
                },
                "required": [],
            },
            handler=fetch_dgcu_news,
        ),
        Tool(
            name="fetch_dgcu_article",
            description=(
                "获取东莞城市学院官网指定文章的详细内容。"
                "传入文章链接，返回文章标题和正文内容。"
                "当用户需要查看某条新闻/文章的具体内容时使用。"
            ),
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "文章链接地址，可以是相对路径如 /news/123.html 或完整URL",
                    }
                },
                "required": ["url"],
            },
            handler=fetch_dgcu_article,
        ),
        Tool(
            name="search_dgcu_page",
            description=(
                "获取东莞城市学院官网指定页面的内容。"
                "支持获取学校概况、党建之窗等页面。"
                "当用户需要了解学校简介、基本情况或特定栏目信息时使用。"
            ),
            parameters_schema_override={
                "type": "object",
                "properties": {
                    "page_type": {
                        "type": "string",
                        "description": "页面类型：about(学校概况)、dan.html(党建之窗)，或具体页面路径",
                        "default": "about",
                    }
                },
                "required": [],
            },
            handler=search_dgcu_page,
        ),
    ]