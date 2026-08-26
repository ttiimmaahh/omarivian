"""Static guards for the QML the panel renders.

Qt's Text defaults to Text.AutoText, which runs Qt.mightBeRichText() and hands
anything that looks like markup to the HTML renderer. Several of the strings the
panel shows come straight from the Rivian API, so a rich-text Text would let a
vehicle "name" fetch a remote <img> from the Quickshell process. The panel renders
no markup by design, so every Text must pin Text.PlainText -- including ones added
later, which is what these tests are for.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
QML_FILES = ("Panel.qml", "BarWidget.qml")


def text_blocks(source: str):
    """Yield (line number, indent, body lines) for every `Text {` element."""
    lines = source.split("\n")
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)Text \{\s*$", line)
        if not match:
            continue
        depth, end = 0, index
        while end < len(lines):
            depth += lines[end].count("{") - lines[end].count("}")
            if depth == 0 and end > index:
                break
            end += 1
        yield index + 1, match.group(1), lines[index:end + 1]


class QmlTextFormatTests(unittest.TestCase):
    def test_every_text_element_pins_plain_text(self):
        checked = 0
        for name in QML_FILES:
            source = (REPO / name).read_text()
            for line_number, indent, block in text_blocks(source):
                checked += 1
                declared = [
                    row.strip() for row in block
                    if re.match(rf"^{re.escape(indent)}  textFormat\s*:", row)
                ]
                self.assertEqual(
                    declared, ["textFormat: Text.PlainText"],
                    f"{name}:{line_number} must declare exactly `textFormat: Text.PlainText`",
                )
        # Guard against the parser silently matching nothing.
        self.assertGreaterEqual(checked, 20)

    def test_no_qml_file_enables_a_markup_text_format(self):
        for name in QML_FILES:
            source = (REPO / name).read_text()
            for bad in ("Text.RichText", "Text.StyledText", "Text.AutoText", "Text.MarkdownText"):
                self.assertNotIn(bad, source, f"{name} must not enable {bad}")

    def test_text_element_count_matches_plain_text_declarations(self):
        for name in QML_FILES:
            source = (REPO / name).read_text()
            self.assertEqual(
                len(re.findall(r"^\s*Text \{\s*$", source, re.MULTILINE)),
                source.count("textFormat: Text.PlainText"),
                f"{name} has a Text element without textFormat",
            )


if __name__ == "__main__":
    unittest.main()
