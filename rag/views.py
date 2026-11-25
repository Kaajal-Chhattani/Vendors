from html.parser import HTMLParser

# class _TextExtractor(HTMLParser):
#     def __init__(self):
#         super().__init__()
#         self._skip = False
#         self.parts = []

#     def handle_starttag(self, tag, attrs):
#         if tag in ('script', 'style'):
#             self._skip = True

#     def handle_endtag(self, tag):
#         if tag in ('script', 'style'):
#             self._skip = False

#     def handle_data(self, data):
#         if not self._skip:
#             stripped = data.strip()
#             if stripped:
#                 self.parts.append(stripped)


# def extract_text_from_html(html):
#     parser = _TextExtractor()
#     parser.feed(html)
#     return '\n'.join(parser.parts)
