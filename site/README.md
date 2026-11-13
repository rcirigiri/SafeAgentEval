# SafeAgentEval website

A zero-dependency static site (`index.html`, `styles.css`, `script.js`)
— no build step. It presents the project the way a product site does:
hero, an interactive graded-run demo (three flagship hazards from the
public packs), how evaluation works, the scenario-pack catalog, the
state-vs-output comparison, and a quickstart.

## Preview locally

From the repository root:

```bash
python -m http.server 8901
# open http://localhost:8901/site/
```

Serving from the repository root matters: the page references brand
assets at `../docs/assets/brand/`. Opening `index.html` as a file also
works, with the same relative layout.

## Deploying

Publish the repository root with any static host (GitHub Pages via
Actions, Netlify, Cloudflare Pages) and point the entry at
`site/index.html`, keeping `docs/assets/brand/` reachable at the
relative path above. All content is static; the demo runs entirely in
the browser.

## Content rules

- Statistics on the page (pack counts, scenario counts, gate counts)
  must match the README pack catalog — update both together.
- The demo cases are illustrative runs of real public scenarios and
  must stay labelled as such, with scenario IDs shown.
- No customer or prospect logos/names: prospective partners are not
  customers, and the page must not imply adoption or endorsement.
