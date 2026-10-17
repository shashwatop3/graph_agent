"""The quake desk team, as a team file.

    reports    stream     the agencies' bulletins and what accounts post, as they arrive
    router     router     links each report to what it is about
    hazard     agent      the quake: keeps the most authoritative figures and passes them on
    risk       agent      the fabs: rates each fab's exposure from the figures it was sent;
                          checks claims about a fab with the fab's own sensors
    ops        responder  the only node with outward tools: alerts the fabs, and re-issues an
                          alert when what it rested on changes
    checker    code       tests what was told against evidence; quarantines lying sources

As in the life pack, the nodes that read untrusted reports cannot act on the world, and the node
that can act reads no reports: only the assessments the risk desk sent it.
"""

from graph_agent.frame.spec import LinkSpec, NodeSpec, Settings, TeamSpec, Trigger

WAKE = [Trigger(on="item"), Trigger(on="message"), Trigger(on="change"), Trigger(on="exposure")]

HAZARD = NodeSpec(
    id="hazard",
    type="agent",
    label="Hazard desk",
    role="hazard desk: the earthquake's magnitude and depth",
    goals=(
        "Keep the earthquake's magnitude (quake.magnitude) and depth (quake.depth_km). When "
        "sources disagree, the most authoritative one counts. Send risk the figures that count, "
        "once each, and send the new ones when a more authoritative source revises them. Never "
        "pass on a figure from an unknown account."
    ),
    triggers=WAKE,
)

RISK = NodeSpec(
    id="risk",
    type="agent",
    label="Risk desk",
    role="risk desk: how exposed each fab is",
    goals=(
        "For every fab, work out its exposure with exposure_rule from the magnitude and depth "
        "that count, record it (assert_belief, predicate fab.exposure, value high, medium or "
        "low, depends_on the magnitude and depth beliefs you used) and send it to ops. When a "
        "figure you used changes, retract the assessments that rested on it and make new ones. "
        "If anyone claims something about a fab (fab.status), check it with fab_status first."
    ),
    triggers=WAKE,
    tools=["exposure_rule", "fab_status"],
)

OPS = NodeSpec(
    id="ops",
    type="responder",
    label="Fab ops",
    role="fab operations: alerts the fabs",
    goals=(
        "Send each fab the alert its latest assessment calls for (fab_alert, depends_on the "
        "assessment belief you were sent). Look at fab_alerts first so you do not send the same "
        "alert twice. When an alert is HELD because the assessment it rested on changed, wait for "
        "the new assessment and send the alert it calls for."
    ),
    triggers=[Trigger(on="message"), Trigger(on="change"), Trigger(on="approval")],
    tools=["fab_alerts", "fab_alert"],
)


def desk_team() -> TeamSpec:
    nodes = [
        NodeSpec(
            id="reports",
            type="stream",
            label="Reports",
            config={"feed": "reports", "when": "start"},
        ),
        NodeSpec(id="router", type="router", label="Router", config={"fallback": "hazard"}),
        HAZARD,
        RISK,
        OPS,
        NodeSpec(id="checker", type="checker", label="Checker"),
    ]
    links = [
        LinkSpec(kind="feeds", src="reports", dst="router"),
        LinkSpec(kind="owns", src="hazard", dst="type:Quake"),
        LinkSpec(kind="owns", src="risk", dst="type:Fab"),
        LinkSpec(kind="talks_to", src="hazard", dst="risk"),
        LinkSpec(kind="talks_to", src="risk", dst="ops"),
        LinkSpec(kind="watches", src="ops", dst="risk"),
    ]
    return TeamSpec(
        name="Quake desk: Hualien, April 2024",
        pack="hualien",
        description=(
            "Early and reviewed figures for a real quake, and a rumour; the risk desk rates three "
            "fabs and ops alerts them."
        ),
        settings=Settings(ticks=6, budget=3000, max_steps=12, quarantine="team"),
        nodes=nodes,
        links=links,
    )


TEAMS = {"desk": desk_team}
