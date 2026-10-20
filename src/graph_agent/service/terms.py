"""The hosted console's terms page (/terms), which Google's OAuth consent screen can link to.

Keep it in step with privacy.py and with what the console does. GRAPH_AGENT_CONTACT is the address
it names for questions.
"""

import html
import os

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Groundwork terms</title>
<style>
  :root {{ --bg: #eef1f3; --ink: #141b24; --muted: #5b6676; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #0d1219; --ink: #e4e9ef; --muted: #8d99a8; }}
  }}
  body {{ background: var(--bg); color: var(--ink); font: 15px/1.55 system-ui, sans-serif;
         max-width: 680px; margin: 0 auto; padding: 24px 16px; }}
  h1 {{ font-size: 24px; }} h2 {{ font-size: 17px; margin-top: 24px; }}
  small {{ color: var(--muted); }}
</style></head><body>
<h1>Groundwork: terms of service</h1>
<p>Groundwork is a research console for running teams of AI agents on simulated data, or on your
own Gmail and Calendar if you connect them. By signing in you accept these terms.</p>

<h2>Using it</h2>
<ul>
<li>It is provided as is, with no promise that it is always available or free of mistakes. It may
change or stop at any time.</li>
<li>Agents are run by a model and can be wrong. Check what they say before you act on it.</li>
<li>Use it lawfully, and only with accounts and data that are yours or that you may use.</li>
<li>Do not try to break it, overload it, or reach other people's data.</li>
</ul>

<h2>Your keys and accounts</h2>
<p>Runs on a model use <b>your own</b> Anthropic key, so the model's cost is billed to you and its
use is covered by the
<a href="https://www.anthropic.com/legal/commercial-terms">terms of your Anthropic account</a>.
Keep your keys safe. Connecting Gmail and Calendar gives Groundwork read-only access, and you can
revoke it at any time from
<a href="https://myaccount.google.com/permissions">your Google account</a>.</p>

<h2>Your data</h2>
<p>What is kept, and where it goes, is on the <a href="/privacy">privacy page</a>. You can delete
all of it at any time with "Delete my account" under My apps, Your keys.</p>

<h2>Liability</h2>
<p>To the extent the law allows, Groundwork's operator is not liable for losses from using it,
including from anything an agent says or does.</p>

<p><small>Questions: {contact}</small></p>
</body></html>
"""


def page() -> str:
    contact = os.environ.get("GRAPH_AGENT_CONTACT", "the person who runs this console")
    return PAGE.format(contact=html.escape(contact))
