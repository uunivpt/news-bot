"""Normalize publisher markup once, before it reaches reader-facing copy."""
import html
import re
from bs4 import BeautifulSoup


def source_text(value, *, paragraphs=False):
    value = html.unescape(str(value or "")[:100_000])
    text = value
    if re.search(r"<[a-zA-Z!/]", value):
        document = BeautifulSoup(value, "html.parser")
        for node in document.select("script,style,noscript,template,iframe,svg"):
            node.decompose()
        if paragraphs:
            for node in document.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "blockquote", "br"]):
                node.insert_before("\n")
                node.insert_after("\n")
        text = document.get_text(" ")
    if paragraphs:
        text = "\n".join(line for raw in text.splitlines() if (line := " ".join(raw.split())))
    else:
        text = " ".join(text.split())
    return re.sub(r"[^\S\n]+([,.;:!?।])", r"\1", text)
