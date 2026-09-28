# Plex Label Manager for Seerr

A separate Docker app that adds selected Plex access labels to movies or TV shows requested in Seerr. It supports multiple labels and no label by default. It preserves existing Plex labels. Unchecking a label stops future automation but does not remove labels already applied to Plex.

## Publish through GitHub

1. Create a GitHub repository named `plex-label-manager` and upload the **contents** of this folder to its root. The default branch should be `main`. Never upload a real `.env` file, API key, Plex token, or password.
2. In GitHub, open **Actions → Publish container image → Run workflow**, or push to `main`. The workflow builds and publishes `ghcr.io/<owner>/plex-label-manager:latest`, plus an immutable commit SHA tag. GitHub's `GITHUB_TOKEN` handles publishing; no registry publishing token is needed in the repository.
3. The GHCR package may initially be private. For a private image, add a GHCR registry in Portainer with a GitHub username and a classic personal access token with `read:packages`, then select that registry for the endpoint. Alternatively, make the package public if you are comfortable publishing this source/image; public GHCR packages can be pulled without credentials. Keep a private package private if preferred.
4. In `compose.portainer.yaml`, replace `REPLACE_WITH_OWNER` with your lowercase GitHub account or organization name. If the repository is given another name, change the image name too. Paste the edited Compose file into **Portainer → Stacks → Add stack → Web editor**, or host it in the repository and deploy the Stack from Git. Do not use the local `compose.yaml` in Portainer: it is for a local source build.
5. Under the Portainer Stack environment variables, define `SEERR_URL`, `SEERR_API_KEY`, `PLEX_URL`, `PLEX_TOKEN`, `APP_PASSWORD`, and `SESSION_SECRET`. Generate `SESSION_SECRET` with `openssl rand -hex 32`. Use Seerr's API key from Settings → General. Point URLs to addresses reachable **from the container**, not `localhost` unless the service really lives inside this same container.
6. If you use `http://seerr:5055` or `http://plex:32400`, join this service to the Docker network those containers use. Otherwise enter reachable LAN addresses for Seerr and Plex. Deploy the Stack. The example publishes the page only on the Docker host's loopback address, at `http://localhost:8088`; use your existing HTTPS reverse proxy for access from another computer. If you intentionally want direct LAN access, change the port mapping to `8088:8080` and restrict access appropriately.
7. Log in and select any combination of Anime, Shared, Kids, Teen, Unavailable, or Hide. All unchecked is the default. Back up the `label_data` volume, which stores your selections.

## Operation and updates

The app polls Seerr every 120 seconds. It uses Seerr's Plex rating key when present and otherwise matches Plex items by TMDB/TVDB GUID. It labels the *show* for TV requests, covering the series. Requests already in Seerr can also be labeled. It retries after an import or transient error. The UI shows waiting and error states.

Each push to `main` publishes a new image. Portainer or your existing image updater can pull the new `latest` image and recreate this container; its named data volume persists. A commit SHA tag is also available if you prefer controlled updates. Watchtower can continue updating stock Seerr and Plex independently. Check a newly imported title in Plex once before relying on its visibility for shared users.

## Local build alternative

Use `.env.example` as a template for a private `.env`, then run `docker compose up -d --build` on the Docker host. This uses `compose.yaml` and builds from the files in this folder.
