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


HONORIFIC = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Shri|Smt|Sr|Jr)\.$", re.I)


def complete_excerpt(value, limit=460):
    """Keep intact standfirsts and shorten long ones at genuine boundaries."""
    text = source_text(value)
    if len(text) <= limit and not HONORIFIC.search(text):
        return text
    ends = (m.end() for m in re.finditer(r"[.!?।](?=\s|$)", text)
            if m.end() <= limit and not HONORIFIC.search(text[:m.end()]))
    return text[:max(ends, default=0)].strip()


def reader_headline(title, context):
    if re.match(r"^(?:असे|असं)\s", title or ""):
        for sentence in re.split(r"(?<=[.!?।])\s+", source_text(context)):
            if 5 <= len(sentence.split()) <= 24 and not re.match(r"^(?:असे|असं)\s", sentence):
                return sentence.rstrip(".।")
    return title
