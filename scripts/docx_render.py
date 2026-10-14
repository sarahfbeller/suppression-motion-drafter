"""The motion and memo as Word files, for the website.

The motion puts each sentence's citation in a footnote. The memo is render.render_memo's Markdown
turned into Word paragraphs, so the two outputs can't drift apart.

Needs python-docx (the website loads it in the browser; locally, `pip install python-docx`).
python-docx has no footnote API, so Footnotes below writes that part of the file directly.
"""
import io
import re

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import CONTENT_TYPE as CT, RELATIONSHIP_TYPE as RT
from docx.opc.packuri import PackURI
from docx.opc.part import XmlPart
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

import render as R

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
SINGLE = '<w:spacing w:after="0" w:line="240" w:lineRule="auto"/>'
# Word expects these two special footnotes (the line above the notes) before any real one.
FOOTNOTES_XML = (f'<w:footnotes {W}>'
                 f'<w:footnote w:type="separator" w:id="-1"><w:p><w:pPr>{SINGLE}</w:pPr>'
                 f'<w:r><w:separator/></w:r></w:p></w:footnote>'
                 f'<w:footnote w:type="continuationSeparator" w:id="0"><w:p><w:pPr>{SINGLE}</w:pPr>'
                 f'<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>'
                 f'</w:footnotes>')
FOOTNOTE_SIZE = Pt(10)

# Memo Markdown inline marks: **bold** and *italic* (case names).
INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")


def add_text(paragraph, text, bold=False, size=None):
    """Add text, printing *Name* in italics (case names, as in memo and motion text)."""
    for i, chunk in enumerate(text.split("*")):
        if chunk:
            run = paragraph.add_run(chunk)
            run.bold = bold or None
            run.italic = (i % 2 == 1) or None
            if size:
                run.font.size = size


def add_markdown(paragraph, text, bold=False, size=None):
    """Add one line of memo Markdown: **bold** spans and *italic* spans."""
    for chunk in INLINE_RE.split(text):
        if chunk.startswith("**") and chunk.endswith("**") and len(chunk) > 4:
            add_text(paragraph, chunk[2:-2], bold=True, size=size)
        elif chunk:
            add_text(paragraph, chunk, bold=bold, size=size)


class Footnotes:
    """The document's footnotes part, created on first use."""

    def __init__(self, document):
        self.part = XmlPart(PackURI("/word/footnotes.xml"), CT.WML_FOOTNOTES,
                            parse_xml(FOOTNOTES_XML), document.part.package)
        document.part.relate_to(self.part, RT.FOOTNOTES)
        self.next_id = 1

    def add(self, paragraph, text):
        """Put a footnote mark at the end of paragraph, with text (which may have *italics*) as the note."""
        fid = self.next_id
        self.next_id += 1
        mark = paragraph.add_run()
        mark.font.superscript = True
        mark._r.append(parse_xml(f'<w:footnoteReference {W} w:id="{fid}"/>'))
        note = parse_xml(f'<w:footnote {W} w:id="{fid}"><w:p><w:pPr>{SINGLE}</w:pPr>'
                         f'<w:r><w:rPr><w:vertAlign w:val="superscript"/><w:sz w:val="20"/></w:rPr>'
                         f'<w:footnoteRef/></w:r>'
                         f'<w:r><w:rPr><w:sz w:val="20"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r>'
                         f'</w:p></w:footnote>')
        self.part.element.append(note)
        add_text(Paragraph(note.find(qn("w:p")), None), text, size=FOOTNOTE_SIZE)


def new_document(line_spacing):
    d = docx.Document()
    normal = d.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.line_spacing = line_spacing
    normal.paragraph_format.space_after = Pt(0)
    return d


def save(d):
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def motion_docx(result):
    """The motion's argument sections, with each sentence's citation sentence as a footnote."""
    d = new_document(line_spacing=2)
    if not result["included"]:
        d.add_paragraph(R.render_motion(result).strip())
        return save(d)
    notes = Footnotes(d)
    title = d.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("ARGUMENT").bold = True
    for i, entry in enumerate(result["included"], 1):
        heading = d.add_paragraph()
        heading.paragraph_format.keep_with_next = True
        add_text(heading, f"{R.roman(i)}. {entry['heading']}", bold=True)
        previous = None  # Id. never reaches back into an earlier section (see render.section)
        for para in entry["paragraphs"]:
            body = d.add_paragraph()
            body.paragraph_format.first_line_indent = Pt(36)
            if "fill_in" in para:
                add_text(body, R.fill_in_marker(para["fill_in"]), bold=True)
                continue
            for j, st in enumerate(para["sentences"]):
                add_text(body, ("" if j == 0 else " ") + st["text"])
                if st["authorities"]:
                    cite = R.citation(st["authorities"], previous)
                    notes.add(body, cite + ("" if cite.rstrip("*").endswith(".") else "."))
                    previous = st["authorities"][0] if len(st["authorities"]) == 1 else None
    return save(d)


def memo_docx(markdown):
    """render.render_memo's Markdown as a plain Word document with bold headings."""
    d = new_document(line_spacing=1.15)
    sizes = {"# ": Pt(15), "## ": Pt(13), "### ": Pt(12)}
    for line in markdown.splitlines():
        if not line.strip():
            continue
        level = next((m for m in sizes if line.startswith(m)), None)
        if level:
            p = d.add_paragraph()
            p.paragraph_format.space_before = Pt(14 if level != "### " else 10)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.keep_with_next = True
            add_markdown(p, line[len(level):], bold=True, size=sizes[level])
        elif line.startswith("- "):
            p = d.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(4)
            add_markdown(p, line[2:])
        else:
            p = d.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            add_markdown(p, line)
    return save(d)
