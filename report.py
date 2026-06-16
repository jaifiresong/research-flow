import os
from datetime import datetime


def generate_html_report(topic: str, review_html: str, sources: list[str], output_path: str) -> str:
    """Generate a self-contained HTML report file.

    Args:
        topic: The research topic
        review_html: HTML content from LLM review generation
        sources: List of source URLs used
        output_path: Path to write the HTML file

    Returns:
        The absolute path of the generated file
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sources_html = ""
    for url in sources:
        sources_html += f'<li><a href="{url}" target="_blank">{url}</a></li>\n'

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{topic} - Research Report</title>
<style>
body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 20px;
    line-height: 1.6;
    color: #333;
    background: #fafafa;
}}
h1 {{ color: #1a1a1a; border-bottom: 2px solid #333; padding-bottom: 10px; }}
h2 {{ color: #2c3e50; margin-top: 30px; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
ul {{ padding-left: 20px; }}
li {{ margin: 4px 0; }}
a {{ color: #3498db; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.meta {{ color: #777; font-size: 0.9em; margin-bottom: 20px; }}
.sources {{ background: #fff; padding: 15px; border: 1px solid #eee; border-radius: 4px; }}
</style>
</head>
<body>
<div class="meta">
    Generated on {timestamp} | Sources: {len(sources)}
</div>

{review_html}

<h2>References</h2>
<div class="sources">
<ol>
{sources_html}
</ol>
</div>
</body>
</html>"""

    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return os.path.abspath(output_path)
