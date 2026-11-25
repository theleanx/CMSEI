# Security

Report vulnerabilities privately to the maintainer contact shown on the site's /terms page. Do not open a public issue for a security problem. Expect an acknowledgement within 5 working days.

In scope: the web app, API, reviewer console, event pipeline (prompt injection, allowlist bypass, schema bypass), and anything that could leak user input or session tokens.

Design points that tests cover: CSRF on every form post, strict CSP with no inline script, hashed session tokens, no IP storage, GET-only CORS, outbound fetches limited to an exact-host allowlist with no redirects, model output validated against a fixed schema before it can touch a score, and a hold queue for high-impact events.

Known limits: rate limiting is in-process. The admin console uses HTTP Basic over TLS with one shared password; put it behind your identity provider before adding more than one reviewer.
