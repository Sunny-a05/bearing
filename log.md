# Log

Chronological record of ingests, edits and lint passes. Newest last.

Format: `## [YYYY-MM-DD] <type> | <title>`, followed by a bulleted list of what was
touched. Types: `ingest` · `edit` · `lint` · `library` · `session`.

## [2026-08-19] feature | Bearing UI — brass/gold design with spinning gear gimmick

- **Color palette:** swapped repo-wide accent from terracotta to brass/gold (#d4a853). One CSS variable, so every button, active state, link, and graph legend updated automatically. Graph view's hardcoded edge color synced to match.
- **Gear mark:** sidebar logo is now a spinning brass cog (slow idle 16s, speeds to 2.4s on hover). Pairs with the "bearing" product name and fits the idea of a planner-researcher as a mechanism that turns rough ideas into sharp ones.
- **Gear-tooth divider:** dashed brass strip under the sidebar header as a visual accent (cheaper than a full SVG gear-tooth border, effective enough).
- **Active nav tick:** whichever page you're viewing gets a tiny fast-spinning gear next to its label. Live state indicator; the gear motif shows up as behavior, not just logo.
- **Subtitle:** sidebar now reads "grill · chart · research" instead of duplicate "Bearing / Bearing", doubling as a reminder of the three-stage loop.
- **Interactive component:** built Gear.tsx (GearIcon + GearMark) as a reusable primitive for future spinners. Spin animations configured via Tailwind classes (gear-spin, gear-spin-fast).
- **Verified:** graph renders 17 nodes (up from 15), dev server running clean, no console errors. All changes route through CSS variables for easy future re-theming.

## [2026-08-19] feature | Add context setup templates (about-me and preferences)

- **wiki/context/about-me.md:** user setup template for AI agents to understand who you are, how you think about plans, current projects, constraints, and success metrics. Agents read this on boot (via CLAUDE.md instructions) to tailor grilling and research to your situation.
- **wiki/context/preferences.md:** AI agent configuration — communication style, question batching, research depth, archive policy, escalation preferences, source trust. Agents use this to work in your idiom without re-asking every session.
- **Graph integration:** both pages appear immediately in the graph visualization as context-type nodes. Graph now has 17 nodes (was 15). They're in the index under the Context section, so they're discoverable.
- **Workflow:** user fills in about-me and preferences once, then Bearing reads them on every session start. No need to re-introduce yourself to the AI.
