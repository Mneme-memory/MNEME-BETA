"""Convert GIVE-TO-CLAUDE-FOR-HELP.txt to PDF with basic markdown-like formatting."""

from fpdf import FPDF
from fpdf.enums import XPos, YPos
import re
import sys
from pathlib import Path

INPUT = Path(__file__).parent.parent / "docs" / "GIVE-TO-CLAUDE-FOR-HELP.txt"
OUTPUT = Path(__file__).parent.parent / "GIVE-TO-CLAUDE-FOR-HELP.pdf"


class Doc(FPDF):
    def header(self):
        pass

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(160, 160, 160)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)


def strip_inline(text):
    """Remove bold/italic/code markers and return plain text for fpdf multi_cell."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)  # markdown links → label
    return text


def render(pdf, line, in_code):
    """Render a single line, returns whether we're still in a code block."""
    stripped = line.rstrip()

    # Code fence toggle
    if stripped.startswith("```"):
        return not in_code

    if in_code:
        pdf.set_font("Mono", size=8.5)
        pdf.set_fill_color(240, 240, 240)
        pdf.set_x(18)
        pdf.multi_cell(
            w=pdf.epw - 8, h=5,
            text=stripped if stripped else " ",
            fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        return in_code

    # H1
    if stripped.startswith("# ") and not stripped.startswith("## "):
        pdf.ln(3)
        pdf.set_font("Body", "B", 15)
        pdf.multi_cell(0, 8, strip_inline(stripped[2:]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        return in_code

    # H2
    if stripped.startswith("## "):
        pdf.ln(4)
        pdf.set_font("Body", "B", 12)
        pdf.multi_cell(0, 7, strip_inline(stripped[3:]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)
        return in_code

    # H3
    if stripped.startswith("### "):
        pdf.ln(3)
        pdf.set_font("Body", "B", 10.5)
        pdf.multi_cell(0, 6, strip_inline(stripped[4:]), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return in_code

    # H4 / bold label lines (#### or ##### )
    if stripped.startswith("#### ") or stripped.startswith("##### "):
        text = re.sub(r'^#{4,6} ', '', stripped)
        pdf.ln(2)
        pdf.set_font("Body", "B", 10)
        pdf.multi_cell(0, 6, strip_inline(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return in_code

    # Horizontal rule
    if stripped in ("---", "***", "___"):
        pdf.ln(2)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        return in_code

    # Bullet point
    if re.match(r'^[-*] ', stripped):
        text = strip_inline(stripped[2:])
        pdf.set_font("Body", size=9.5)
        # Bullet
        pdf.set_x(pdf.l_margin + 4)
        pdf.cell(5, 5, "\u2022")
        pdf.set_x(pdf.l_margin + 9)
        pdf.multi_cell(pdf.epw - 9, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return in_code

    # Numbered list
    m = re.match(r'^(\d+)\. (.+)', stripped)
    if m:
        text = strip_inline(m.group(2))
        pdf.set_font("Body", size=9.5)
        pdf.set_x(pdf.l_margin + 4)
        pdf.cell(7, 5, m.group(1) + ".")
        pdf.set_x(pdf.l_margin + 11)
        pdf.multi_cell(pdf.epw - 11, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        return in_code

    # Inline bold paragraph (starts with **Word:**)
    if re.match(r'^\*\*[^*]+\*\*', stripped):
        # Split into bold label + rest
        m2 = re.match(r'^\*\*(.+?)\*\*\s*(.*)', stripped)
        if m2:
            label, rest = m2.group(1), strip_inline(m2.group(2))
            pdf.ln(1)
            pdf.set_font("Body", "B", 9.5)
            pdf.write(5.5, label + (" " if rest else ""))
            if rest:
                pdf.set_font("Body", size=9.5)
                pdf.write(5.5, rest)
            pdf.ln(5.5)
            return in_code

    # Empty line
    if not stripped:
        pdf.ln(2.5)
        return in_code

    # Normal paragraph
    pdf.set_font("Body", size=9.5)
    pdf.multi_cell(0, 5.5, strip_inline(stripped), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return in_code


def main():
    text = INPUT.read_text(encoding="utf-8")
    lines = text.splitlines()

    pdf = Doc(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(auto=True, margin=18)

    # Use Unicode-capable TTF fonts from Windows
    winfonts = Path("C:/Windows/Fonts")
    pdf.add_font("Body", style="", fname=str(winfonts / "arial.ttf"))
    pdf.add_font("Body", style="B", fname=str(winfonts / "arialbd.ttf"))
    pdf.add_font("Body", style="I", fname=str(winfonts / "ariali.ttf"))
    pdf.add_font("Body", style="BI", fname=str(winfonts / "arialbi.ttf"))
    pdf.add_font("Mono", style="", fname=str(winfonts / "cour.ttf"))

    pdf.add_page()
    pdf.set_text_color(20, 20, 20)

    in_code = False
    for line in lines:
        in_code = render(pdf, line, in_code)

    pdf.output(str(OUTPUT))
    print(f"Saved: {OUTPUT}")


if __name__ == "__main__":
    main()
