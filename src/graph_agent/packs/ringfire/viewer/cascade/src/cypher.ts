// The FalkorDB queries behind each step of a belief chain, as in src/graph_agent/stores/falkor.py
// (support_routes, expose, _downstream). Shown next to the chain so the graph's part is visible.

export const SUPPORT_ROUTES = `MATCH (o:Observation)-[:SUPPORTS]->(b:Belief {id: $id})
OPTIONAL MATCH (o)-[r:RELAYED_VIA]->(a:Agent)
RETURN o.id, collect([r.hop, a.id])`;

export const EXPOSE_RECOUNT = `MATCH (b:Belief {owner: $viewer}) WHERE b.status IN ['active', 'suspect']
MATCH (o:Observation)-[:SUPPORTS]->(b)
OPTIONAL MATCH (o)-[:RELAYED_VIA]->(a:Agent)
WITH b, o, collect(a.id) AS route
WITH b, sum(CASE WHEN size([x IN route WHERE x IN $exposed]) = 0
            THEN 1 ELSE 0 END) AS alive_now
SET b.support_routes = alive_now
RETURN b.id, b.status, alive_now`;

export const DOWNSTREAM = `MATCH (s:Node)<-[:DERIVED_FROM]-(d)
WHERE s.id IN $frontier AND d.owner = $viewer
RETURN DISTINCT d.id, labels(d), d.status`;
