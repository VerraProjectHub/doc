#!/usr/bin/env python3
import argparse
import html
import re
import sys
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "releases/source/2026-release-notes.docx"
OUTPUT = ROOT / "releases/index.html"

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": WORD_NS, "r": REL_NS, "rel": PACKAGE_REL_NS}

VERSION_RE = re.compile(r"^V\s*\d+(?:\.\d+)?\b.*", re.IGNORECASE)
TICKET_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:#\s*\d+|PR\s*#?\s*\d+|VER\s*-?\s*\d+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)
BARE_TICKET_RE = re.compile(r"(?<![A-Za-z0-9])\d{4,6}(?![A-Za-z0-9])")
TICKET_URL_RE = re.compile(
    r"https?://[^\s)]+(?:/_workitems/edit/|atlassian\.net/browse/|/_git/[^/\s]+/commit/)[^\s)]*",
    re.IGNORECASE,
)


@dataclass
class Paragraph:
    text: str
    style: str
    font_size: int
    links: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ReleaseSection:
    title: str
    points: list[Paragraph] = field(default_factory=list)
    anchor: str = ""


@dataclass
class Release:
    title: str
    status: str = ""
    notes: list[Paragraph] = field(default_factory=list)
    sections: list[ReleaseSection] = field(default_factory=list)
    anchor: str = ""


def element_text(element: ET.Element) -> str:
    parts = []
    for child in element.iter():
        name = child.tag.rsplit("}", 1)[-1]
        if name == "t":
            parts.append(child.text or "")
        elif name == "tab":
            parts.append("\t")
        elif name == "br":
            parts.append("\n")
    return "".join(parts).strip()


def read_document() -> tuple[list[Paragraph], dict[str, str]]:
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Release notes source file not found: {SOURCE}")

    with ZipFile(SOURCE) as archive:
        document = ET.fromstring(archive.read("word/document.xml"))
        relationships = ET.fromstring(archive.read("word/_rels/document.xml.rels"))

    relation_targets = {
        relation.get("Id"): relation.get("Target", "")
        for relation in relationships.findall("rel:Relationship", NS)
    }

    paragraphs = []
    for element in document.find("w:body", NS).findall(".//w:p", NS):
        text = element_text(element)
        if not text:
            continue

        style_element = element.find("w:pPr/w:pStyle", NS)
        style = style_element.get(f"{{{WORD_NS}}}val", "Normal") if style_element is not None else "Normal"
        sizes = [
            int(size.get(f"{{{WORD_NS}}}val", "0"))
            for size in element.findall(".//w:rPr/w:sz", NS)
            if size.get(f"{{{WORD_NS}}}val", "").isdigit()
        ]
        links = []
        for link in element.findall("w:hyperlink", NS):
            relation_id = link.get(f"{{{REL_NS}}}id")
            target = relation_targets.get(relation_id, "")
            label = element_text(link)
            if target.startswith("https://verra.clickup.com/") and label:
                links.append((label, target))

        paragraphs.append(Paragraph(text, style, max(sizes, default=0), links))

    return paragraphs, relation_targets


def clean_text(value: str) -> str:
    value = TICKET_URL_RE.sub("", value)

    def clean_parenthetical(match: re.Match[str]) -> str:
        contents = match.group(1)
        has_ticket_reference = bool(TICKET_RE.search(contents))
        contents = TICKET_RE.sub("", contents)
        if has_ticket_reference:
            contents = BARE_TICKET_RE.sub("", contents)
            if not re.search(r"[A-Za-z0-9]", contents):
                return ""
            return f"({contents})"

        if re.fullmatch(r"[\s,#;]*\d{4,6}[\s,#;]*", contents):
            return ""
        if re.fullmatch(r"[\s,#;]*\d{4,6}(?:\s*,\s*\d{4,6})+[\s,#;]*", contents):
            return ""
        return f"({contents})"

    value = re.sub(r"\(([^()]*)\)", clean_parenthetical, value)
    value = TICKET_RE.sub("", value)
    value = re.sub(r"\s+\d{4,6}(?=[.,;]?$)", "", value)
    value = re.sub(r"\(\s*(?:,\s*)*\)", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\s+([,.;])", r"\1", value)
    return value.strip()


def is_section_heading(paragraph: Paragraph) -> bool:
    return (
        paragraph.font_size >= 36
        and len(paragraph.text) <= 80
        and not VERSION_RE.match(paragraph.text)
        and paragraph.text.casefold() not in {
            "up coming",
            "how you can help",
            "how to provide feedback",
        }
    )


def parse_releases(paragraphs: list[Paragraph]):
    title = "Project Hub Release Notes"
    year = ""
    introduction = ""
    status = ""
    releases: list[Release] = []
    closing: dict[str, list[Paragraph]] = {}
    current: Release | None = None
    closing_key: str | None = None

    for paragraph in paragraphs:
        text = paragraph.text
        if paragraph.style == "Heading1" and not releases:
            title = text
            continue
        if paragraph.style == "Title" and not releases:
            year = text
            continue
        if text.casefold() == "up coming" and not releases:
            status = text
            continue
        if VERSION_RE.match(text):
            current = Release(text, status=status if not releases else "")
            status = ""
            releases.append(current)
            closing_key = None
            continue
        if text.casefold() in {"how you can help", "how to provide feedback"}:
            closing_key = text.casefold()
            closing.setdefault(closing_key, [])
            current = None
            continue
        if closing_key:
            closing[closing_key].append(paragraph)
            continue
        if current is None:
            if not introduction and paragraph.style == "Normal":
                introduction = text
            continue
        if is_section_heading(paragraph):
            current.sections.append(ReleaseSection(text))
        elif current.sections:
            current.sections[-1].points.append(paragraph)
        else:
            current.notes.append(paragraph)

    if not releases:
        raise ValueError("The Word document does not contain any version headings.")
    if not any(release.title for release in releases):
        raise ValueError("The Word document contains no usable release notes.")

    releases[0].status = releases[0].status or ""
    return title, year, introduction, releases, closing


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def render_text(paragraph: Paragraph, emphasized: bool = False) -> str:
    text = clean_text(paragraph.text)
    rendered = html.escape(text)
    for label, target in paragraph.links:
        label = clean_text(label)
        if not label:
            continue
        safe_label = html.escape(label)
        safe_target = html.escape(target, quote=True)
        anchor = (
            f'<a href="{safe_target}" target="_blank" rel="noopener noreferrer">'
            f"{safe_label}</a>"
        )
        rendered = rendered.replace(safe_label, anchor, 1)

    if emphasized and " – " in text:
        heading, remainder = text.split(" – ", 1)
        return f"<strong>{html.escape(heading)}</strong> – {html.escape(remainder)}"
    return rendered


def assign_anchors(releases: list[Release]) -> None:
    for index, release in enumerate(releases):
        release.anchor = "latest" if index == 0 else f"release-{slug(release.title)}"
        used = set()
        for section in release.sections:
            base = f"{release.anchor}-{slug(section.title)}"
            anchor = base
            suffix = 2
            while anchor in used:
                anchor = f"{base}-{suffix}"
                suffix += 1
            used.add(anchor)
            section.anchor = anchor


STYLE = """\
      :root { color-scheme: light; --ink: #0e2b64; --paper: #e2e9f1; --muted: #526073; --line: #bfcbd9; font-family: "Be Vietnam Pro", Arial, sans-serif; font-synthesis: none; text-rendering: optimizeLegibility; }
      * { box-sizing: border-box; }
      html { scroll-behavior: smooth; scroll-padding-top: 1rem; }
      body { min-width: 320px; min-height: 100vh; margin: 0; background: var(--paper); color: #253348; }
      a { color: #1d4ed8; }
      .page-layout { display: grid; grid-template-columns: 320px minmax(0, 1fr); align-items: stretch; min-height: 100vh; }
      .release-index { position: sticky; top: 0; height: 100vh; height: 100dvh; overflow-y: auto; padding: 20px 10px 32px; border-right: 1px solid var(--line); background: #fff; }
      .release-index h2 { margin: 0 12px 12px; color: #6b7a8d; font-size: .76rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
      .toc-sections, .toc-subitems { margin: 0; padding: 0; list-style: none; }
      .toc-section { border-bottom: 1px solid #eef1f5; }
      .toc-main-row { display: flex; align-items: center; gap: 6px; padding: 3px; border-radius: 6px; }
      .toc-main-row:hover, .toc-main-row.active { background: #eff3f8; }
      .toc .top { flex: 1; min-width: 0; padding: 7px 8px; border-radius: 6px; color: #526073; font-size: .81rem; font-weight: 600; line-height: 1.4; text-decoration: none; }
      .toc .top:hover, .toc-main-row.active .top { color: #1d4ed8; }
      .toc-toggle { display: inline-flex; flex: 0 0 30px; width: 30px; height: 30px; align-items: center; justify-content: center; padding: 0; border: 0; border-radius: 6px; background: transparent; color: #94a3b8; cursor: pointer; }
      .toc-toggle:hover { background: #eff3f8; }
      .toc-toggle:focus-visible, .toc a:focus-visible { outline: none; box-shadow: 0 0 0 3px rgba(37, 99, 235, .25); }
      .toc-chevron { width: 8px; height: 8px; border-right: 2px solid currentColor; border-bottom: 2px solid currentColor; transform: rotate(45deg) translate(-2px, -2px); transition: transform 180ms ease; }
      .toc-toggle[aria-expanded="true"] .toc-chevron { transform: rotate(225deg) translate(-2px, -2px); }
      .toc-subitems { max-height: 0; overflow: hidden; visibility: hidden; }
      .toc-subitems.expanded { max-height: 2000px; visibility: visible; }
      .toc-subitems a { display: block; margin: 0 4px 3px 20px; padding: 6px 10px; border-left: 2px solid #dde4ee; border-radius: 0 6px 6px 0; color: #526073; font-size: .76rem; line-height: 1.4; text-decoration: none; overflow-wrap: anywhere; }
      .toc-subitems a:hover, .toc-subitems a.active { border-left-color: #2563eb; background: #eff6ff; color: #1d4ed8; }
      .toc a[aria-current="location"] { background: #eff6ff; color: #1d4ed8; }
      .page-main { width: 100%; min-width: 0; margin: 0; padding: 24px 24px 64px; }
      .page-heading { margin-bottom: 18px; padding: clamp(24px, 4vw, 42px); border: 1px solid var(--line); border-radius: 18px; background: #fff; box-shadow: 0 10px 30px rgba(14, 43, 100, .07); }
      .page-year { margin: 0 0 .4rem; color: #15803d; font-size: .8rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
      .page-heading h1 { margin: 0 0 .7rem; color: var(--ink); font-size: clamp(1.8rem, 3.8vw, 2.5rem); font-weight: 700; letter-spacing: -.04em; }
      .page-heading p:last-child { max-width: 760px; margin: 0; color: var(--muted); line-height: 1.7; }
      .release-card, .closing-section { overflow: hidden; margin-bottom: 18px; border: 1px solid var(--line); border-radius: 18px; background: #fff; box-shadow: 0 10px 30px rgba(14, 43, 100, .07); }
      .release-heading { padding: clamp(20px, 4vw, 34px); background: linear-gradient(135deg, var(--ink) 0%, #19386e 100%); color: #fff; }
      .release-heading h2 { margin: 0; color: #fff; font-size: clamp(1.25rem, 2.6vw, 1.75rem); font-weight: 600; line-height: 1.35; }
      .release-status { display: inline-block; margin-bottom: .65rem; padding: .25rem .55rem; border: 1px solid rgba(255,255,255,.5); border-radius: 999px; color: #e6f4d7; font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
      .release-note, .release-section, .closing-section > p, .closing-section > ul { margin: 0; padding: 18px clamp(20px, 4vw, 34px); color: var(--muted); font-size: .92rem; line-height: 1.75; }
      .release-note + .release-section, .release-section + .release-section, .release-note + .release-note, .release-section + .release-note { border-top: 1px solid #e8edf3; }
      .release-section h3 { margin: 0 0 .7rem; color: #15803d; font-size: 1.05rem; font-weight: 600; }
      .release-points { display: grid; gap: .55rem; margin: 0; padding: 0; list-style: none; }
      .release-points li { position: relative; padding-left: 1.15rem; color: var(--muted); font-size: .9rem; line-height: 1.7; overflow-wrap: anywhere; }
      .release-points li::before { position: absolute; top: .7em; left: 0; width: 5px; height: 5px; border-radius: 50%; background: #15803d; content: ""; }
      .release-points a { overflow-wrap: anywhere; }
      .closing-section h2 { margin: 0; padding: 20px clamp(20px, 4vw, 34px); background: linear-gradient(135deg, var(--ink) 0%, #19386e 100%); color: #fff; font-size: 1.35rem; }
      .closing-section > p, .closing-section > ul { padding-top: 12px; padding-bottom: 12px; }
      .closing-section > p + ul, .closing-section > ul + p { padding-top: 0; }
      #latest, .release-section, .closing-section { scroll-margin-top: 1rem; }
      @media (max-width: 900px) {
        .page-layout { grid-template-columns: minmax(0, 1fr); }
        .release-index { position: relative; height: auto; max-height: 44dvh; border-right: 0; border-bottom: 1px solid var(--line); }
        .page-main { padding: 18px 14px 48px; }
      }
      @media (max-width: 520px) { .page-main { padding: 16px 10px 40px; } .release-heading { padding: 20px; } }
      @media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } .toc-chevron { transition: none; } }
"""


def render_sidebar(releases: list[Release]) -> str:
    rows = []
    for index, release in enumerate(releases):
        label = f"Latest: {release.title.removeprefix('V ')}" if index == 0 else release.title
        if release.sections:
            control_id = f"toc-{release.anchor}"
            expanded = index == 0
            expanded_attr = "true" if expanded else "false"
            class_name = ' class="toc-subitems expanded"' if expanded else ' class="toc-subitems"'
            section_links = "".join(
                f'<li><a href="#{section.anchor}">{html.escape(section.title)}</a></li>'
                for section in release.sections
            )
            rows.append(
                '<li class="toc-section"><div class="toc-main-row">'
                f'<a class="top" href="#{release.anchor}">{html.escape(label)}</a>'
                f'<button class="toc-toggle" type="button" aria-label="Toggle sections for '
                f'{html.escape(release.title, quote=True)}" aria-expanded="{expanded_attr}" '
                f'aria-controls="{control_id}"><span class="toc-chevron" aria-hidden="true"></span></button>'
                f'</div><ul{class_name} id="{control_id}">{section_links}</ul></li>'
            )
        else:
            rows.append(
                '<li class="toc-section"><div class="toc-main-row">'
                f'<a class="top" href="#{release.anchor}">{html.escape(label)}</a>'
                '</div></li>'
            )
    return "\n".join(rows)


def render_release(release: Release, index: int) -> str:
    heading_id = f"release-title-{slug(release.title)}"
    status = (
        f'<span class="release-status">{html.escape(release.status)}</span>'
        if index == 0 and release.status
        else ""
    )
    content = [
        f'<section class="release-card" id="{release.anchor}" aria-labelledby="{heading_id}">',
        f'<header class="release-heading">{status}<h2 id="{heading_id}">{html.escape(release.title)}</h2></header>',
    ]
    for paragraph in release.notes:
        text = render_text(paragraph)
        if text:
            content.append(f'<p class="release-note">{text}</p>')
    for section in release.sections:
        content.append(
            f'<section class="release-section" aria-labelledby="{section.anchor}">'
            f'<h3 id="{section.anchor}">{html.escape(section.title)}</h3>'
        )
        if section.points:
            points = "".join(
                f"<li>{render_text(point)}</li>"
                for point in section.points
                if clean_text(point.text)
            )
            if points:
                content.append(f'<ul class="release-points">{points}</ul>')
        content.append("</section>")
    content.append("</section>")
    return "\n".join(content)


def render_closing(title: str, paragraphs: list[Paragraph], kind: str) -> str:
    if not paragraphs:
        return ""
    heading_id = slug(title)
    content = [
        f'<section class="closing-section" id="{heading_id}" aria-labelledby="{heading_id}-title">',
        f'<h2 id="{heading_id}-title">{html.escape(title)}</h2>',
    ]
    if kind == "help":
        intro = paragraphs[0]
        content.append(f"<p>{render_text(intro)}</p>")
        points = paragraphs[1:]
        if points:
            rendered = []
            for point in points:
                text = clean_text(point.text)
                if not text:
                    continue
                if " – " in text:
                    label, remainder = text.split(" – ", 1)
                    rendered.append(f"<li><strong>{html.escape(label)}</strong> – {html.escape(remainder)}</li>")
                else:
                    rendered.append(f"<li>{render_text(point)}</li>")
            if rendered:
                content.append(f'<ul class="release-points">{"".join(rendered)}</ul>')
    else:
        if paragraphs:
            content.append(f"<p>{render_text(paragraphs[0])}</p>")
        bullet_labels = {
            "report any technical issues or bugs in the project hub applications",
            "suggest new features or improvements",
            "propose ideas for entirely new applications",
        }
        bullets = []
        remaining = []
        for paragraph in paragraphs[1:]:
            if clean_text(paragraph.text).casefold() in bullet_labels:
                bullets.append(f"<li>{render_text(paragraph)}</li>")
            else:
                remaining.append(paragraph)
        if bullets:
            content.append(f'<ul class="release-points">{"".join(bullets)}</ul>')
        content.extend(f"<p>{render_text(paragraph)}</p>" for paragraph in remaining)
    content.append("</section>")
    return "\n".join(content)


def render_page(paragraphs: list[Paragraph]) -> str:
    title, year, introduction, releases, closing = parse_releases(paragraphs)
    assign_anchors(releases)
    help_notes = closing.get("how you can help", [])
    feedback_notes = closing.get("how to provide feedback", [])

    body = [
        "<!doctype html>",
        '<html lang="en">',
        "  <head>",
        '    <meta charset="utf-8">',
        '    <meta name="viewport" content="width=device-width, initial-scale=1">',
        f'    <meta name="description" content="{html.escape(year)} Project Hub release notes and product updates.">',
        '    <meta name="theme-color" content="#0e2b64">',
        f"    <title>{html.escape(title)} | Verra</title>",
        '    <link rel="preconnect" href="https://fonts.googleapis.com">',
        '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        '    <link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap" rel="stylesheet">',
        "    <style>",
        STYLE.rstrip(),
        "    </style>",
        "  </head>",
        "  <body>",
        '    <div class="page-layout">',
        '      <nav class="release-index toc" aria-label="Release notes index">',
        "        <h2>Contents</h2>",
        f'        <ul class="toc-sections">{render_sidebar(releases)}</ul>',
        "      </nav>",
        '      <main class="page-main">',
        '        <header class="page-heading">',
        f'          <p class="page-year">{html.escape(year)}</p>',
        f"          <h1>{html.escape(title)}</h1>",
        f"          <p>{html.escape(clean_text(introduction))}</p>",
        "        </header>",
    ]
    body.extend(f"        {render_release(release, index)}" for index, release in enumerate(releases))
    if help_notes:
        body.append(f'        {render_closing("How You Can Help", help_notes, "help")}')
    if feedback_notes:
        body.append(f'        {render_closing("How to Provide Feedback", feedback_notes, "feedback")}')
    body.extend(
        [
            "      </main>",
            "    </div>",
            "    <script>",
            "      (function () {",
            '        var links = Array.prototype.slice.call(document.querySelectorAll(\'.release-index a[href^="#"]\'));',
            "        var targets = links.map(function (link) { return document.getElementById(link.hash.slice(1)); });",
            "        var toggles = document.querySelectorAll('.toc-toggle');",
            "",
            "        toggles.forEach(function (button) {",
            "          button.addEventListener('click', function () {",
            "            var list = document.getElementById(button.getAttribute('aria-controls'));",
            "            if (!list) return;",
            "            var expanded = button.getAttribute('aria-expanded') === 'true';",
            "            button.setAttribute('aria-expanded', String(!expanded));",
            "            list.classList.toggle('expanded', !expanded);",
            "          });",
            "        });",
            "",
            "        function expandHashTarget() {",
            "          var link = links.find(function (item) { return item.hash === window.location.hash; });",
            "          var list = link && link.closest('.toc-subitems');",
            "          if (list) {",
            "            list.classList.add('expanded');",
            "            var button = list.previousElementSibling.querySelector('.toc-toggle');",
            "            if (button) button.setAttribute('aria-expanded', 'true');",
            "          }",
            "          if (link && window.location.hash) {",
            "            window.requestAnimationFrame(function () {",
            "              var target = document.getElementById(window.location.hash.slice(1));",
            "              if (target) target.scrollIntoView();",
            "            });",
            "          }",
            "        }",
            "",
            "        function updateActiveLink() {",
            "          var current = 0;",
            "          targets.forEach(function (target, index) {",
            "            if (target && target.getBoundingClientRect().top <= 120) current = index;",
            "          });",
            "          links.forEach(function (link, index) {",
            '            if (index === current) link.setAttribute("aria-current", "location");',
            '            else link.removeAttribute("aria-current");',
            "          });",
            "          if (links[current]) {",
            "            var linkList = links[current].closest('.toc-subitems');",
            "            if (linkList && !linkList.classList.contains('expanded')) {",
            "              linkList.classList.add('expanded');",
            "              var button = linkList.previousElementSibling.querySelector('.toc-toggle');",
            '              if (button) button.setAttribute("aria-expanded", "true");',
            "            }",
            "          }",
            "        }",
            "",
            "        window.addEventListener('scroll', updateActiveLink, { passive: true });",
            "        window.addEventListener('hashchange', function () { expandHashTarget(); updateActiveLink(); });",
            "        expandHashTarget();",
            "        updateActiveLink();",
            "      })();",
            "    </script>",
            "  </body>",
            "</html>",
            "",
        ]
    )
    return "\n".join(body)


class PageValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.fragments: list[str] = []
        self.visible_text: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
        href = attributes.get("href", "")
        if href.startswith("#"):
            self.fragments.append(href[1:])
        if tag in {"style", "script"}:
            self.skipping += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"style", "script"} and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.visible_text.append(data)


def validate_page(page: str) -> None:
    validator = PageValidator()
    validator.feed(page)
    duplicates = sorted({item for item in validator.ids if validator.ids.count(item) > 1})
    missing = sorted({fragment for fragment in validator.fragments if fragment not in validator.ids})
    visible_text = " ".join(validator.visible_text)
    if duplicates:
        raise ValueError(f"Generated page has duplicate IDs: {duplicates[:5]}")
    if missing:
        raise ValueError(f"Generated page has broken bookmarks: {missing[:5]}")
    if "latest" not in validator.ids:
        raise ValueError("Generated page has no #latest bookmark.")
    if TICKET_RE.search(visible_text):
        raise ValueError("Generated page still contains a ticket reference.")
    if TICKET_URL_RE.search(page):
        raise ValueError("Generated page still contains a ticket URL.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the Release Notes page from the Word source.")
    parser.add_argument("--check", action="store_true", help="Fail if the generated page is not up to date.")
    args = parser.parse_args()

    paragraphs, _ = read_document()
    page = render_page(paragraphs)
    validate_page(page)

    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text() != page:
            print(f"{OUTPUT.relative_to(ROOT)} is out of date; regenerate it with this script.", file=sys.stderr)
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is up to date.")
        return 0

    OUTPUT.write_text(page)
    print(f"Generated {OUTPUT.relative_to(ROOT)} from {SOURCE.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
