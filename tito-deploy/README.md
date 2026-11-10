# Tito deploy

One-liner (run as root on a fresh Ubuntu 24.04 VPS):

    curl -fsSL https://raw.githubusercontent.com/Forzalab/open-webui/tito/tito-deploy/bootstrap.sh | bash

- First run: installs Docker, unattended-upgrades (security only), ufw, swap,
  clones the repo, and copies `tito-deploy/.env.example` to `/opt/tito/.env`.
- It prints `edit /opt/tito/.env then rerun` and stops if a required var is empty.
- Edit `/opt/tito/.env`, then rerun the same one-liner to start the stack.

Logs:

    docker compose -f /opt/tito/open-webui/tito-deploy/docker-compose.yml \
      --env-file /opt/tito/.env logs -f

Update = rerun the one-liner (fetches the pinned ref and rebuilds).

The image is built by GitHub Actions; the ghcr package must be PUBLIC (or `docker login` on the box).

## Fast deploy
- Push to `tito` → thin image (~1-2 min): `Dockerfile.tito` = `tito-base` + our backend.
- After an upstream sync (or first time): run "Build and publish Tito image" with `base` = true.
- Tests are opt-in: put `[test]` in the commit message, or run the workflow with `test` = true.
