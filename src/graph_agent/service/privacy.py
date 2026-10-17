"""The hosted console's privacy page (/privacy), which Google's OAuth verification asks for.

It says what the code does, so keep it in step: what is kept (users.py), what is asked of Google
(auth.py), where mail goes (a model, with the person's own key), how to delete it all (DELETE
/api/me). GRAPH_AGENT_CONTACT is the address it names for questions.
"""

import html
import os

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Cascade privacy</title>
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
<h1>Cascade: privacy</h1>
<p>Cascade runs teams of AI agents on simulated data, or on your own Gmail and Calendar if you
connect them. This page says what it keeps and where your data goes.</p>

<h2>What is kept</h2>
<ul>
<li>Your Google account's id, address and name, from signing in.</li>
<li>The keys you add (your Anthropic key, app tokens such as Todoist's) and, if you connect
Gmail and Calendar, Google's refresh token. All of these are encrypted, used only for your own
runs, and never shown again, not even to you.</li>
<li>Your apps, your teams, and a cache of the questions your runs asked the model and its
answers, so that a run made again costs nothing.</li>
<li>Your runs, in memory only: they are dropped after a few hours, or when you start more.</li>
</ul>

<h2>Google data</h2>
<p>Connecting Gmail and Calendar asks Google for <b>read-only</b> access
(gmail.readonly, calendar.readonly). Cascade cannot send, delete, label or change anything in
your mail or calendar. Mail and events are read only while a run of yours is going, to give to
your own agents, and the cache above keeps what they were asked about. They are not used to
train models, shown to other people, sold, or used for advertising.</p>
<p>Cascade's use and transfer of information received from Google APIs adheres to the
<a href="https://developers.google.com/terms/api-services-user-data-policy">Google API Services
User Data Policy</a>, including its Limited Use requirements.</p>

<h2>Where your data goes</h2>
<p>To run your agents, the text they read (for example a mail) is sent to Anthropic's API
under <b>your own</b> Anthropic key, as the
<a href="https://www.anthropic.com/legal/commercial-terms">terms of your Anthropic account</a>
describe. Apps you add (such as Todoist) are reached with your own tokens. Nothing goes anywhere
else.</p>

<h2>Deleting it</h2>
<p>Under My apps, Your keys, "Delete my account" removes everything kept for you and revokes
Cascade's access at Google. You can also revoke that access at any time from
<a href="https://myaccount.google.com/permissions">your Google account</a>.</p>

<p><small>Questions: {contact}</small></p>
</body></html>
"""


def page() -> str:
    contact = os.environ.get("GRAPH_AGENT_CONTACT", "the person who runs this console")
    return PAGE.format(contact=html.escape(contact))
