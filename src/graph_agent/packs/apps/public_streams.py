"""The streams a team can read with no account and no key: `{"preset": "usgs-quakes"}` in a
team's streams is all it takes (frame/streams.py says what each field means).

Each one was read on 2026-10-18 and answered without a key. Each says how much it sends, so a
team is not drowned: a firehose (Bluesky, Wikipedia) needs a `keep` filter of yours, and at most
`most` items reach the team a poll anyway. "trusted": an agency's own record, whose items are
evidence; the rest are hearsay, from senders who can be caught lying.

Not here, and why (also 2026-10-18): Mastodon's public stream wants a token now; Reddit refuses
scripts (403); GDELT allows one request in five seconds from an address, which a shared server
cannot keep to; CertStream's public server sent nothing; ReliefWeb's API is gone (410).
"""

from typing import Any

# a status page made with Atlassian Statuspage (most are): its incidents, each update once
STATUSPAGE = {
    "kind": "poll",
    "every": 120,
    "items": "incidents",
    "id": "id",
    "title": "name",
    "fields": ["name", "status", "impact", "updated_at", "incident_updates.0.body"],
    "trusted": True,
}

TOPICS: dict[str, list[str]] = {
    "Earthquakes and disasters": [
        "usgs-quakes",
        "emsc-quakes",
        "jma-quakes",
        "gdacs-alerts",
        "nws-alerts",
        "uk-floods",
        "space-weather",
    ],
    "People talking": ["bluesky-posts", "wikipedia-edits", "hacker-news", "bbc-world"],
    "Software and security": [
        "github-status",
        "cloudflare-status",
        "anthropic-status",
        "github-advisories",
        "cisa-exploited",
    ],
    "Getting about": ["london-tube"],
    "Markets (prices only)": ["coinbase-btc"],
}

PUBLIC: dict[str, dict[str, Any]] = {
    # ---- earthquakes and disasters -------------------------------------------------------------
    "usgs-quakes": {
        "label": "USGS: earthquakes, magnitude 4.5 and up",
        "about": (
            "The US Geological Survey's quakes of the last day, worldwide, a few an hour. A quake "
            "comes again when it is revised (its status turns from automatic to reviewed)."
        ),
        "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson",
        "items": "features",
        "id": "id",
        "title": "properties.title",
        "fields": [
            "properties.title",
            "properties.mag",
            "properties.magType",
            "properties.place",
            "properties.time|ms",
            "geometry.coordinates",
            "properties.status",
            "properties.tsunami",
            "properties.alert",
            "properties.url",
        ],
        "trusted": True,
    },
    "emsc-quakes": {
        "label": "EMSC: earthquakes, magnitude 4 and up",
        "about": (
            "The European-Mediterranean Seismological Centre's latest quakes, worldwide, with the "
            "agency that measured each (auth). Often minutes ahead of USGS, and its magnitude "
            "can differ."
        ),
        "url": "https://www.seismicportal.eu/fdsnws/event/1/query?limit=20&format=json&minmag=4",
        "items": "features",
        "id": "id",
        "title": "properties.flynn_region",
        "fields": [
            "properties.flynn_region",
            "properties.mag",
            "properties.magtype",
            "properties.time",
            "properties.lat",
            "properties.lon",
            "properties.depth",
            "properties.auth",
        ],
        "trusted": True,
    },
    "jma-quakes": {
        "label": "Japan Meteorological Agency: quakes felt in Japan",
        "about": (
            "Every quake felt in Japan, many a day, small ones too: a first report, then the "
            "detailed one (maxi: the highest shindo seen)."
        ),
        "url": "https://www.jma.go.jp/bosai/quake/data/list.json",
        "id": "eid",
        "title": "en_anm",
        "fields": ["en_ttl", "en_anm", "at", "mag", "maxi", "cod"],
        "trusted": True,
    },
    "gdacs-alerts": {
        "label": "GDACS: disaster alerts",
        "about": (
            "The UN and EU's Global Disaster Alert and Coordination System: earthquakes, "
            "cyclones, floods, volcanoes and fires, with an alert level and who is exposed. A "
            "few a day; the page is large, so it is read every 5 minutes."
        ),
        "url": "https://www.gdacs.org/xml/rss.xml",
        "format": "rss",
        "every": 300,
        "id": "guid",
        "title": "title",
        "fields": [
            "title",
            "description",
            "eventtype",
            "alertlevel",
            "country",
            "fromdate",
            "datemodified",
            "link",
        ],
        "trusted": True,
    },
    "nws-alerts": {
        "label": "US National Weather Service: severe alerts",
        "about": "Severe weather warnings in force in the US: tornadoes, floods, storms, fires.",
        "url": "https://api.weather.gov/alerts/active?status=actual&severity=Severe",
        "every": 120,
        "items": "features",
        "id": "properties.id",
        "title": "properties.headline",
        "fields": [
            "properties.event",
            "properties.headline",
            "properties.areaDesc",
            "properties.onset",
            "properties.ends",
            "properties.description",
        ],
        "trusted": True,
    },
    "uk-floods": {
        "label": "Environment Agency: flood warnings in England",
        "about": "Flood alerts and warnings in force in England, each as its level changes.",
        "url": "https://environment.data.gov.uk/flood-monitoring/id/floods",
        "every": 300,
        "items": "items",
        "id": "floodAreaID",
        "title": "description",
        "fields": ["description", "severity", "eaAreaName", "timeRaised", "message"],
        "trusted": True,
    },
    "space-weather": {
        "label": "NOAA: space weather alerts",
        "about": "Geomagnetic storm watches, solar radiation and radio blackout alerts.",
        "url": "https://services.swpc.noaa.gov/products/alerts.json",
        "every": 300,
        "id": "issue_datetime",
        "title": "product_id",
        "fields": ["issue_datetime", "message"],
        "trusted": True,
    },
    # ---- people talking ------------------------------------------------------------------------
    "bluesky-posts": {
        "label": "Bluesky: public posts",
        "kind": "websocket",
        "about": (
            "Every public post on Bluesky as it is made, about thirty a second: give it words "
            "to keep (keep commit.record.text). Each poster is a sender of their own."
        ),
        "url": "wss://jetstream2.us-east.bsky.network/subscribe?wantedCollections=app.bsky.feed.post",
        "id": "commit.cid",
        "sender": "did",
        "title": "commit.record.text",
        "fields": ["commit.record.text", "commit.record.createdAt", "commit.record.langs"],
        "keep": {"commit.operation": "^create$"},
        "limit": 1200,
    },
    "wikipedia-edits": {
        "label": "Wikipedia: edits as they are made",
        "kind": "events",
        "about": (
            "Every edit to English Wikipedia, a few a second: give it the pages to watch (keep "
            "title). Each editor is a sender of their own."
        ),
        "url": "https://stream.wikimedia.org/v2/stream/recentchange",
        "id": "id",
        "sender": "user",
        "title": "title",
        "fields": [
            "title",
            "user",
            "comment",
            "bot",
            "length.old",
            "length.new",
            "timestamp|s",
            "notify_url",
        ],
        "keep": {"wiki": "^enwiki$", "type": "^edit$", "namespace": "^0$"},
    },
    "hacker-news": {
        "label": "Hacker News: new stories",
        "about": "Stories as they are posted, a few a minute (keep title for a topic).",
        "url": "https://hn.algolia.com/api/v1/search_by_date?tags=story&hitsPerPage=30",
        "items": "hits",
        "id": "objectID",
        "sender": "author",
        "title": "title",
        "fields": ["title", "url", "author", "created_at"],
    },
    "bbc-world": {
        "label": "BBC News: world",
        "about": "The BBC's world news headlines, a few an hour.",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "format": "rss",
        "every": 300,
        "id": "guid",
        "title": "title",
        "fields": ["title", "description", "pubDate", "link"],
    },
    # ---- software and security -----------------------------------------------------------------
    "github-status": {
        "label": "GitHub status: incidents",
        "about": "GitHub's own incidents and every update to them.",
        "url": "https://www.githubstatus.com/api/v2/incidents.json",
        **STATUSPAGE,
    },
    "cloudflare-status": {
        "label": "Cloudflare status: incidents",
        "about": "Cloudflare's own incidents and every update to them.",
        "url": "https://www.cloudflarestatus.com/api/v2/incidents.json",
        **STATUSPAGE,
    },
    "anthropic-status": {
        "label": "Anthropic status: incidents",
        "about": "Anthropic's (Claude's) own incidents and every update to them.",
        "url": "https://status.claude.com/api/v2/incidents.json",
        **STATUSPAGE,
    },
    "github-advisories": {
        "label": "GitHub: security advisories",
        "about": (
            "New reviewed advisories for open-source packages (keep "
            "vulnerabilities.0.package.ecosystem for npm, pip, go...). GitHub allows 60 reads an "
            "hour without a key, so it is read every 10 minutes."
        ),
        "url": "https://api.github.com/advisories?per_page=20&type=reviewed",
        "every": 600,
        "id": "ghsa_id",
        "title": "summary",
        "fields": [
            "summary",
            "severity",
            "cve_id",
            "vulnerabilities.0.package.ecosystem",
            "vulnerabilities.0.package.name",
            "vulnerabilities.0.vulnerable_version_range",
            "published_at",
            "html_url",
        ],
        "trusted": True,
    },
    "cisa-exploited": {
        "label": "CISA: vulnerabilities exploited in the wild",
        "about": (
            "The US agency's list of flaws known to be exploited, a few a week (a large page, "
            "read every hour)."
        ),
        "url": (
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
        ),
        "every": 3600,
        "items": "vulnerabilities",
        "id": "cveID",
        "title": "vulnerabilityName",
        "fields": [
            "cveID",
            "vendorProject",
            "product",
            "vulnerabilityName",
            "dateAdded",
            "shortDescription",
            "knownRansomwareCampaignUse",
            "dueDate",
        ],
        "trusted": True,
    },
    # ---- getting about -------------------------------------------------------------------------
    "london-tube": {
        "label": "Transport for London: tube lines",
        "about": "Each tube line's status, again whenever it changes (delays, closures).",
        "url": "https://api.tfl.gov.uk/Line/Mode/tube/Status",
        "every": 120,
        "id": "id",
        "title": "name",
        "fields": [
            "name",
            "lineStatuses.0.statusSeverityDescription",
            "lineStatuses.0.reason",
        ],
        "most": 11,
        "trusted": True,
    },
    # ---- markets -------------------------------------------------------------------------------
    "coinbase-btc": {
        "label": "Coinbase: bitcoin price",
        "kind": "websocket",
        "about": (
            "Bitcoin's price on Coinbase as it trades, a few times a second (the team gets the "
            "newest few each poll). Prices only: nothing here can trade."
        ),
        "url": "wss://ws-feed.exchange.coinbase.com",
        "hello": {"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]},
        "title": "product_id",
        "fields": ["product_id", "price", "best_bid", "best_ask", "volume_24h", "time"],
        "keep": {"type": "^ticker$"},
        "most": 2,
        "trusted": True,
    },
}
