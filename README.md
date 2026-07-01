# House Hunt 2026

Interactive property search tracker for our multi-generational house move.

## Live site

https://its-not-rocket-science.github.io/house/

## First-time setup

1. Open the live site
2. Click **⚙ GitHub Token** in the top-right header
3. Paste your fine-grained personal access token (see below)
4. Click **Save token** — you'll see **✓ GitHub Connected**

Anyone who needs to add notes or photos does the same one-time token paste on their device.

## Creating the token

Go to https://github.com/settings/personal-access-tokens/new

- Token name: `house-app`
- Expiration: No expiration (or 1 year)
- Repository access: Only select repositories → **its-not-rocket-science/house**
- Permissions:
  - Contents: **Read and write**
  - Pages: **Read and write**
  - Actions: **Read**
  - Metadata: **Read** (auto-selected)

## Features

- **Map** — all properties plotted, colour-coded by rank
- **Filters** — by area cluster, annexe status, viewing status, caveats
- **Property cards** — ranked list with quick-view details
- **Detail panel** — full description, Rightmove photos, links to listing and contact form
- **Status tracking** — mark as Active / Viewing booked / Offer made / Rejected
- **Notes** — add notes per property, saved to this repo and synced across devices
- **Visit photos** — upload photos from viewings, stored in `data/photos/` in this repo
- **Viewing dates** — record when you visited each property

## File structure

```
index.html              — the app
data/
  properties.json       — all 37 properties with rankings and metadata
  notes.json            — notes, visit dates and photo references (auto-updated by app)
  photos/
    <ref>/              — visit photos per property (uploaded via app)
.github/
  workflows/
    deploy.yml          — auto-deploys to GitHub Pages on every push
```

## Updating properties

Edit `data/properties.json` directly and push — the site redeploys automatically within ~60 seconds.

The `status` field for each property can be: `active`, `viewing-booked`, `offer-made`, `rejected`.
