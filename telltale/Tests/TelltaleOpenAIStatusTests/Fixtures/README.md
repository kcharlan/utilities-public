Synthetic OpenAI status-page fixtures live here. Every value is invented: ids look like
`synthetic-01`, names are made up, and links use `status.example.com`. The files follow the
field shapes in spec section 10, written by hand rather than copied from a live response.

- `summary_incident.json`: a summary with two ongoing incidents, each shaped like an incident detail (no `updated_at`; one timestamp has a 2-digit fraction); components as a list.
- `summary_quiet.json`: a summary with no ongoing incidents; components as an id-to-name map.
- `incident_detail.json`: one incident's detail (updates and component impacts).
- `feed.rss`: the RSS fallback, two items.
- `error_page.html`: an HTML error page returned with a success status.
