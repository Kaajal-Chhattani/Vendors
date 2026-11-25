import os
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from chat.service import ingest


class FakePage:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_open(pages):
    return mock.patch.object(ingest.pdfplumber, "open", return_value=FakePdf([FakePage(t) for t in pages]))


class ExtractPdfTableTests(SimpleTestCase):
    def test_no_table_raises(self):
        with fake_open([[]]):
            with self.assertRaises(ingest.NoTableFound):
                ingest.extract_pdf_table("x.pdf")

    def test_header_only_table_is_ignored(self):
        with fake_open([[[["Name", "Sales"]]]]):
            with self.assertRaises(ingest.NoTableFound):
                ingest.extract_pdf_table("x.pdf")

    def test_table_split_over_pages_is_merged(self):
        page1 = [[["Name", "Sales"], ["A", "1"]]]
        page2 = [[["Name", "Sales"], ["B", "2"]]]
        with fake_open([page1, page2]):
            rows, count = ingest.extract_pdf_table("x.pdf")
        self.assertEqual(rows, [["Name", "Sales"], ["A", "1"], ["B", "2"]])
        self.assertEqual(count, 2)

    def test_largest_table_wins_and_cells_are_cleaned(self):
        small = [["X", "Y"], ["1", "2"]]
        big = [["Name", "Sales"], [" A \n b ", "1"], ["B", None], ["", ""]]
        with fake_open([[small, big]]):
            rows, count = ingest.extract_pdf_table("x.pdf")
        self.assertEqual(rows, [["Name", "Sales"], ["A b", "1"], ["B", ""]])
        self.assertEqual(count, 2)


class PdfToCsvTests(SimpleTestCase):
    def test_writes_csv_and_pads_short_rows(self):
        table = [[["Name", "Sales"], ["A"], ["B", "2"]]]
        with fake_open([table]), tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "sub", "t.csv")
            rows, count = ingest.pdf_to_csv("x.pdf", out)
            with open(out, encoding="utf-8") as handle:
                content = handle.read()
        self.assertEqual((rows, count), (2, 1))
        self.assertEqual(content.splitlines(), ["Name,Sales", "A,", "B,2"])


class DocumentCsvPathTests(SimpleTestCase):
    def test_path_is_named_after_the_pdf_without_dedup_suffix(self):
        document = mock.Mock(pk=7)
        document.file.name = "documents/Sales_Report_aB3dE5f.pdf"
        document.file.path = "/srv/documents/Sales_Report_aB3dE5f.pdf"
        self.assertEqual(ingest.document_csv_path(document), "/srv/documents/derived/7/Sales_Report.csv")


import json
import re

from chat.service import langgraph_agents as agents


def _chart_from(output):
    return json.loads(re.search(r"```chart\n([\s\S]*?)\n```", output).group(1))


class MakeChartTests(SimpleTestCase):
    def call(self, **kwargs):
        args = {"chart_type": "bar", "title": "Sales", "labels": ["North", "South"], "values": [120, 90]}
        args.update(kwargs)
        return agents.make_chart.func(**args)

    def test_builds_the_chart_block_the_page_renders(self):
        chart = _chart_from(self.call(series_name="Sales", source="report.pdf"))
        self.assertEqual(chart["type"], "bar")
        self.assertEqual(chart["data"]["labels"], ["North", "South"])
        self.assertEqual(chart["data"]["datasets"], [{"label": "Sales", "data": [120.0, 90.0]}])
        self.assertEqual(chart["meta"]["source"], "report.pdf")

    def test_unknown_chart_type_falls_back_to_bar(self):
        self.assertEqual(_chart_from(self.call(chart_type="3d-pie"))["type"], "bar")

    def test_mismatched_lengths_are_refused(self):
        self.assertIn("same length", self.call(values=[1]))

    def test_empty_is_refused(self):
        self.assertIn("same length", self.call(labels=[], values=[]))

    def test_too_many_points_are_refused(self):
        count = agents.MAX_CHART_POINTS + 1
        self.assertIn("too many", self.call(labels=[str(i) for i in range(count)], values=list(range(count))))


class ReadDocumentTextTests(SimpleTestCase):
    def call(self, documents, **kwargs):
        config = {"configurable": {"conversation": object()}}
        with mock.patch.object(agents, "conversation_documents", return_value=documents):
            return agents.read_document_text.func(config=config, **kwargs)

    def document(self, name, text):
        document = mock.Mock(raw_text=text)
        document.file.name = f"documents/{name}"
        return document

    def test_no_documents(self):
        self.assertIn("No uploaded document", self.call([]))

    def test_returns_text_of_newest_by_default(self):
        output = self.call([self.document("new.pdf", "North 120"), self.document("old.pdf", "x")])
        self.assertIn("new.pdf", output)
        self.assertIn("North 120", output)

    def test_picks_by_name(self):
        output = self.call([self.document("new.pdf", "N"), self.document("old.pdf", "OLD TEXT")], document_name="old")
        self.assertIn("OLD TEXT", output)

    def test_unknown_name_lists_available(self):
        output = self.call([self.document("new.pdf", "N")], document_name="nope")
        self.assertIn("Available documents: new.pdf", output)

    def test_long_text_is_cut_and_says_so(self):
        long_text = "a" * (agents.MAX_DOCUMENT_TEXT_CHARS + 50)
        output = self.call([self.document("big.pdf", long_text)])
        self.assertIn("the rest was cut", output)
        self.assertNotIn("a" * (agents.MAX_DOCUMENT_TEXT_CHARS + 1), output)

    def test_empty_text(self):
        self.assertIn("no readable text", self.call([self.document("blank.pdf", "  ")]))
