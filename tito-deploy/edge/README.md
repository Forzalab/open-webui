# tito-deploy/edge (DRAFT from box, 2026-11-10). Orc: commit on a branch as tito-deploy/edge/.
Order (key exchange, public keys only):
1. box:  sudo EDGE_WG_PUB=placeholder bash box-wg.sh  → prints BOX pub (tunnel down until step 3)
2. edge: sudo EDGE_TLS_INTERNAL=1 BOX_WG_PUB=<box pub> bash edge-up.sh → prints EDGE pub (host = titodori.duckdns.org, self-signed for the dry run)
   test: curl -sk --resolve titodori.duckdns.org:443:8.229.241.31 https://titodori.duckdns.org/health → 200
4. After Tony moves DNS by hand: re-run edge-up.sh WITHOUT EDGE_TLS_INTERNAL → real Let's Encrypt cert.
3. box:  sudo EDGE_WG_PUB=<edge pub> bash box-wg.sh → "edge reachable"
Needed on box: owui must listen on 10.77.0.2:8080. Today owui only exposes 8080 inside the docker network.
  compose owui: add `ports: ["10.77.0.2:8080:8080"]` (bind needs wg0 up first, or use 0.0.0.0 + ufw allow only from wg0).
DECIDED (Tony, O23): edge serves titodori.duckdns.org; DNS moves later by hand after the tunnel test.
Behavior note: box Caddy redirects duckdns browser navigations → sslip. The edge Caddy proxies everything (no redirect). Add the same @browser redir on the edge if that should stay.
Google OAuth redirect URI is tied to the login host. Moving login to the edge means adding the new URI in Google Console.
