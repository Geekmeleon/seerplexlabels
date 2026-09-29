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

## Request and choose labels together

Use **Request with labels** at the top of the app. Search a title, open a movie or show, choose seasons for TV, select any labels, then submit. The app posts the request to Seerr and saves labels against the returned request ID. No labels are selected by default. The existing requests page remains available to label a request submitted directly in Seerr.

This page uses Seerr's configured default Radarr/Sonarr server and quality settings. It does not yet present Seerr's optional server, profile, root folder, and 4K choices. Use Seerr's own request dialog for those choices and then label the item from **Existing requests**. A rejected or already existing request is not relabeled by the new request form; use **Existing requests** for that.

To update an existing GitHub repository, replace `app.py`, `Dockerfile`, `README.md`, and `index.html`; add `request_search.html` and `request_detail.html`. Keep the existing `label_data` volume and Portainer secrets. After GitHub Actions publishes the new image, update the Portainer Stack with **Pull latest image** and recreate the container. If a bind mount is used for `/data`, it must remain writable by UID 10001.


## Flat application files and collection requests

All HTML files now live beside app.py at the repository root. Dockerfile copies root HTML files, and Flask reads templates from that location. The old templates folder can be deleted once after uploading this version. Keep the existing .github/workflows/publish.yml in its required location; it does not need to be changed for routine app updates. The update ZIP contains flat root files and deliberately excludes the workflow and Compose configuration, preserving your current image address, environment, and mount settings.

Movie details include a collection link when Seerr supplies one. Open it to review and request missing movies with the same optional Plex labels. Existing requests and Plex availability are rechecked before submission and skipped. Each selected missing movie creates a separate Seerr request; each outcome is reported. Labels apply only to newly submitted movies. A collection submission can partially succeed; review the outcomes before retrying. TV uses season selection rather than movie collections.

## Plex collection inheritance

On a movie's details page, follow the collection link. The collection page looks up its movies in Plex by external IDs and lists regular collections already used by those movies. Choose a collection name and a label set to inherit; when existing labels differ, choose one explicitly. If no movies are present, enter a new collection name and choose labels. Newly requested movies receive those labels after import, join the chosen collection, and the collection receives the same labels. Existing labels and memberships are preserved; existing movies are skipped and are not relabeled. Smart collections cannot receive manual members. The collection belongs to the library where each requested movie arrives; differently named or cross-library collections require an explicit name choice.

This release keeps application HTML files beside app.py. Upload all application files to the repository root. Keep the existing publishing workflow at .github/workflows/publish.yml. For this update, replace app.py and collection.html (and use the flat-layout Dockerfile if migrating from the old templates folder). Existing SQLite data is migrated automatically; back up /data before upgrading.
