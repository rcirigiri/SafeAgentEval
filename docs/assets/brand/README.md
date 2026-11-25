# agentic-safety-eval brand assets

Master mark: **Speech, verified against the record.** A single gradient
speech bubble (what the agent *said*) carries a bold checkmark over two
ledger lines (what the system of record *shows*) — the framework's whole
thesis in one glyph, legible from 512 px down to a 16 px favicon. The
wordmark is lowercase `agentic-safety-` in navy with `eval` in teal.
The checkmark is part of the identity mark only; it is **not** a
certification seal and must never be used to imply that an agent is
"certified safe." Conformance results are communicated as dated
run records (framework version, scenario-pack version, `provider_trust`
tier), never as badges.

**Lockup tagline:** "State-Verified Agent Safety" — deliberately free of
any domain name, so the identity survives new scenario packs. The vision
sentence it compresses: agentic-safety-eval evaluates whether AI agents act
within their authorized mandate and report their actions truthfully,
verified against independently observed system state, across payments,
commerce, and other state-changing workflows.

## Files

| File | Use |
|---|---|
| `agenticsafetyeval-icon.svg` / `.png` (512/256/128/64/32) | Icon only — slides, favicons, avatars |
| `agenticsafetyeval-icon-dark.png` | Icon recoloured for dark backgrounds |
| `agenticsafetyeval-logo-horizontal.svg` / `.png` | Primary lockup (light backgrounds) |
| `agenticsafetyeval-logo-horizontal-dark.svg` / `.png` | Lockup for dark backgrounds |
| `agenticsafetyeval-logo-horizontal-mono.svg` / `.png` | Single-colour lockup (print, watermarks) |
| `github-social-preview.png` / `.svg` | GitHub repository social preview (1280×640; edit the SVG and re-render) |
| `agenticsafetyeval-linkedin-banner.png` | LinkedIn banner (1584×396; regenerate with `python scripts/build_linkedin_banner.py`) — leads with "Open Source · Apache-2.0", lockup kept right of the profile-photo overlap |
| `agenticsafetyeval-x-banner.png` | X profile banner (3000×1000, 2× the recommended 1500×500; `agenticsafetyeval-x-banner-1500.png` is the 1× fallback; source: `agenticsafetyeval-x-banner.svg`, regenerate with `python scripts/build_x_banner.py`) — do **not** reuse the LinkedIn banner on X (4:1 vs 3:1 crops the right edge). Headline and chips sit right of the profile-photo overlap; the lockup sits above it |
| `author-card.png` | Author card at the bottom of the repository README (1600×560; regenerate with `python scripts/build_author_card.py`) |
| `github-avatar.png` | Padded icon (512×512, white) sized for circular avatar crops |
| `favicon.ico`, `apple-touch-icon.png` | Web favicons |
| `badge-safeorderbench.svg` | Flagship pack name badge (text chip) |

## Colours

- Navy `#0B3C6C` → Teal `#0FA3A8` diagonal gradient (icon; navy end is
  also the wordmark colour, teal highlights `eval`)
- Dark background `#082038` (lockup on dark uses white wordmark text
  with `#2BD4DA` for `eval`)
- Pack badge: SafeOrderBench `#12355B`

## Rules

- Render the name exactly as `agentic-safety-eval` (one word, that capitalisation).
- Do not place the mark beside OWASP, NIST, or payment-network logos in a
  way that implies endorsement.
- Do not create "certified" seals or pass/fail badges from the checkmark.
- Minimum clear space around the lockup: the height of the ledger block.
