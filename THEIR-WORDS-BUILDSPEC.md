# Build Spec — "THEIR WORDS": verbatim quote database + private viewer

> **What you (Claude Code) are building:** a two-surface product for The Initiated
> Father (a men's-circle program, "The Expedition"). Surface 1: a local pipeline
> that harvests **verbatim quotes** from call transcripts into an append-only,
> anonymized canon, with human approval on every entry. Surface 2: a **private,
> read-only web viewer** deployed on Vercel that renders the canon as filterable
> cards and auto-redeploys on every git push.
>
> Build autonomously in the order given under **Build order**. Where a detail is
> unspecified, make a reasonable, documented choice and keep going. The privacy
> rules in §9 are non-negotiable and override convenience everywhere.

---

## 1. Why this exists

The owner (Isaiah) runs cohort calls (squad calls + one-on-ones) that are
automatically recorded, transcribed, and summarized by an existing system (§2).
The men's own words — how they describe their pain, their deferrals, their
fathers, their dream outcomes — are the raw material for session themes,
marketing copy, sales pages, and eventually a book.

**Verbatim or nothing — paraphrase is contamination.** The product's entire
value is that every entry is the man's exact words. No AI cleanup, no
smoothing, no paraphrase features anywhere in this codebase.

Nothing enters the canon without the owner's explicit approval.

---

## 2. The upstream system (already built — consume it, never modify it)

A separate project ("call processor") lives at `~/Documents/audioprocessor` on
the same Mac. It watches `~/Documents/Zoom`, and for every finished call writes
one folder:

```
~/Documents/audioprocessor/output/<slug>/     e.g. 2026-08-01-turbo-squad-call-4-act-i/
    transcript.md      ← verbatim speaker-labeled transcript (the quote source)
    summary.md         ← executive summary (not used by Their Words)
    manifest.json      ← machine-readable index — THE integration contract
    reflections/       ← per-man reflections (not used by Their Words)
```

Its full documentation is `~/Documents/audioprocessor/SYSTEM.md` — read it if
anything here is insufficient.

### 2a. The trigger rule (critical)

Artifacts are written over a span of minutes: transcript first, summary later,
**manifest last and atomically** (temp file + rename). Therefore:

> **A complete `manifest.json` appearing in a call folder is the one and only
> "this call is fully processed" signal. Never trigger on `transcript.md`.**

### 2b. `manifest.json` schema (v1)

```json
{
  "schema_version": 1,
  "call_name": "Turbo Squad: Call 4, Act I",
  "zoom_topic": "Act I",
  "date": "2026-08-01",
  "time": "19:00",
  "duration_seconds": 5520.0,
  "participants": ["Isaiah English", "Scott Sample", "Adam Sample"],
  "owner": "Isaiah",
  "tags": ["squad"],
  "classification": {
    "call_type": "squad",            // "squad" | "one_on_one" | "other" | null
    "squad_name": "Turbo Squad",
    "call_number": 4,
    "other_party": null              // set for one_on_one calls
  },
  "source_folder": "…absolute path…",
  "source_files": ["audioIsaiahEnglish….m4a", "…"],
  "artifacts": {
    "transcript": "/Users/…/audioprocessor/output/<slug>/transcript.md",
    "summary": "…", "reflections": {"…": "…"}, "manifest": "…"
  },
  "profiles_updated": ["…"], "emailed_to": ["…"]
}
```

Notes:
- `tags` here are **call-level selectors** (config-driven keywords: `squad`,
  `expedition`, …) — use them to decide *which calls to ingest*. They are a
  different concept from Their Words' quote-level tags (§5).
- `classification` may be `null` (manual runs, API failure) — fall back to
  `call_name` + `tags`.
- All paths are absolute. Read transcripts **in place** via
  `artifacts.transcript`; do not copy them into this repo's folders.

### 2c. Transcript format (the quote source)

```markdown
# Turbo Squad: Call 4, Act I

- **Date:** 2026-08-01 · 19:00
- **Participants:** Isaiah English, Scott Sample, Adam Sample
…

---

**[00:14:22] Scott Sample:** I keep telling myself I'll be more present when
work slows down. It never slows down. It's been never-slowing-down for six years.

**[00:14:41] Isaiah English:** Say more about "it never slows down."
```

One turn per paragraph: `**[HH:MM:SS] Full Name:** verbatim text`. Timestamps
are seconds from call start on one shared timeline — `slug + timestamp` is a
durable pointer to the exact moment in the source audio.

### 2d. Hard boundary

Their Words **reads** `output/*/manifest.json` and the transcript paths inside
them. It never writes into `~/Documents/audioprocessor/` anything, ever, and
never reads that project's `.env`, `contacts.yaml`, or `profiles/`.

---

## 3. Repo structure (this new repo — private on GitHub)

```
their-words/
  their-words.md          # THE CANON — anonymized (initials only), committed
  their-words.json        # derived machine mirror of the canon, committed
                          #   (regenerated on every approval; the viewer reads this)
  tags.md                 # tag registry: every tag, definition, one example
  TAXONOMY-CHANGELOG.md   # every tag created/merged/split/retired, dated, reason
  roster.yaml             # full name -> canonical initials  — GITIGNORED, local only
  candidates/             # proposed entries awaiting approval — GITIGNORED
  state/ingested.json     # slugs already processed            — GITIGNORED
  transcripts/            # optional local scratch              — GITIGNORED
  viewer/                 # the web viewer (see §7)
  tools/                  # the pipeline CLI (ingest, review, rebuild, taxonomy)
  .gitignore              # roster.yaml, candidates/, state/, transcripts/, .env
```

**What gets pushed to GitHub:** the canon (md + json), tag registry, changelog,
viewer code, tools code. **What never leaves the machine:** roster (real names),
candidates (pre-approval material), state, transcripts, secrets.

---

## 4. Entry schema

Six fields (five from the owner's spec + a stable ID for citing quotes in copy
drafts and the book):

| Field | Rule |
|---|---|
| `id` | `TW-0001`, sequential, never reused, never renumbered |
| `date` | from the manifest (`YYYY-MM-DD`) |
| `man` | initials only, from the roster (§5.2) |
| `context` | derived from `classification`: `Intro call` / `Squad call 4` / `1:1` / `Text` (texts are added manually, §5.6) |
| `quote` | **verbatim, untouched**, with enough surrounding sentences to prevent misreading. Include the `[HH:MM:SS]` timestamp + source slug as provenance. |
| `tags` | one or more from the registry |

In `their-words.md`, entries render human-readable under a regenerated tag
index at the top of the file. `their-words.json` mirrors the same entries as an
array of objects — regenerate both from the same in-memory model on every
approval so they can never drift.

**Seed tags** (write into `tags.md` with definitions at build time):
`the-lie` · `deferral` (log the verb TENSE in a tag note: present = live need,
future = deferral) · `father` · `map-language-adopted` · `dream-outcome` ·
`objection` · `testimonial-seed` · `founder-story-resonance`.

---

## 5. The pipeline (Surface 1 — local CLI)

### 5.1 Ingest (automatic discovery, manual gate)
Scan `~/Documents/audioprocessor/output/*/manifest.json`. For each slug not in
`state/ingested.json` whose call-level `tags` intersect the configured ingest
set (default: `squad`, `expedition`): read the transcript, extract candidate
quotes via the Claude API with proposed quote-level tags, and write them to
`candidates/<slug>.md`. Mark the slug ingested only after the candidate file is
written. Run on demand (`ingest` command) and/or via a lightweight watcher —
same launchd pattern the upstream system uses.

### 5.2 Roster & anonymization
`roster.yaml` maps transcript display names → canonical initials
(`"Scott Sample": SS`). On encountering an unknown participant, prompt the
owner to assign initials (auto-suggest, detect collisions — two men may share
initials; the owner picks a disambiguator like `SS2`). Initials are stable
across cohorts forever.

### 5.3 Owner exclusion
The manifest's `owner` (Isaiah) is a participant on every call. **His turns are
excluded from candidate extraction by default.** Exception: passages where a
*man's response to* the owner's story lands as `founder-story-resonance` — the
quote captured is the man's words, never the owner's.

### 5.4 Review (the human gate)
`review` command: step through each candidate — **approve / edit context
window / kill** — one decision per quote. Approvals get the next `TW-` id,
append to the canon, regenerate the tag index and `their-words.json`, and
`git commit` with a dated message (e.g. `2026-08-01: +6 entries from Turbo
Squad Call 4`). Killed candidates are deleted. Nothing auto-approves.

### 5.5 Taxonomy evolution (on trigger, not autopilot)
- A quote that fits no tag → the candidate carries a proposed new tag (name +
  definition) for approval alongside the quote.
- `review-taxonomy` command — and an automatic prompt every ~25 new entries —
  audits the registry: propose merges of near-duplicates, splits of overloaded
  tags, retirements. Owner approves each change; every change is logged to
  `TAXONOMY-CHANGELOG.md` and re-tags propagate through the canon (and the
  regenerated JSON).

### 5.6 Texts
`add-text` command for manually pasting a text-message quote (date, man,
quote) — same schema, `context: Text`, same approval-commit flow.

---

## 6. Where the data lives (owner's mental model — preserve it)

The database is files on the Mac. Git snapshots every change locally; the
private GitHub repo is the cloud mirror those snapshots push to. Raw
transcripts, the roster, and candidates exist in layer one only — the
`.gitignore` enforces that they can never be pushed. The viewer deploys from
the GitHub mirror, so it can only ever see what was allowed to leave the
machine: the anonymized canon.

---

## 7. The viewer (Surface 2 — private, read-only, on Vercel)

### What it is
A single page that renders `their-words.json` as quote cards. Bookmark-able
URL (`their-words.vercel.app` or a custom domain later). Auto-redeploys on
every push — the git push the owner already does *is* the update mechanism.

### Tech choice — keep it boring
A static page (one `index.html` + CSS + a small JS file) that fetches
`their-words.json` from the same deployment. No framework, no build step, no
dependencies to rot. It reads the **committed JSON** — never parse the
Markdown canon in the browser, and there is no write path of any kind. The
transcripts aren't in the repo, so the viewer *cannot* leak them even in
principle.

### v1 features (needle-movers only)
1. **Cards** — quote, `man`, date, context, tags. Clean typography; quotes are
   the hero, chrome is quiet.
2. **Filter by tag and by man** — clickable chips with live counts
   (`deferral (14)`), AND-combinable, one-click clear.
3. **Full-text search** — instant client-side substring search across quotes.
   For a copywriting corpus this is the single highest-value control ("someone
   said something about drowning…").
4. **Copy button on every card** — one click copies the verbatim quote (and a
   second option: quote + `TW-id` reference). The viewer's job is getting
   quotes *into* copy drafts; make that one click.
5. **Header stats** — total entries, entries this month, last-updated date.
   The "is the corpus growing" glance.
6. **Responsive** — the owner will check this from his phone.

### Deliberately deferred (build only when the corpus earns them)
Timeline visualization, per-man pages, tag co-occurrence charts, export
buttons. At <100 entries they're decoration; revisit at ~250 entries.

### Access protection (the no-vibe-coded-auth rule)
No hand-rolled login. Use **Vercel Deployment Protection** on the project:
- **Vercel Authentication** (available on the free Hobby plan): only the
  owner's logged-in Vercel account can open the URL. Enable it for **all
  deployments including production**. This is the default choice.
- Vercel's **Password Protection** exists as an alternative but requires a
  paid plan — only if the owner later wants to share the URL without a Vercel
  login.
- Also send `X-Robots-Tag: noindex` on all responses (belt and suspenders).

**Acceptance test for protection (mandatory):** open the production URL in a
private/incognito window — you must hit Vercel's auth wall, never the quotes.
Do not ship until this passes.

### Deployment
Private GitHub repo → Vercel "Import Project" → framework preset: none/static,
root directory `viewer/` (or serve the JSON alongside — ensure the deployed
site can fetch the canon JSON committed in the repo). Every push to `main`
redeploys production automatically. Workflow: approve entries → commit+push →
live within a minute.

---

## 8. Config

`config.yaml` (committed, no secrets):
```yaml
upstream_output_dir: ~/Documents/audioprocessor/output
ingest_tags: [squad, expedition]       # call-level tags to ingest
owner_name: Isaiah                     # excluded from extraction (§5.3)
review_taxonomy_every: 25              # entries between taxonomy prompts
model: claude-sonnet-5                 # extraction model
```
`ANTHROPIC_API_KEY` in `.env` (gitignored).

---

## 9. Privacy rules — hard-coded, non-negotiable

1. **Raw transcripts, the roster, and candidates are never stored off-machine**
   — never committed, never pushed, never uploaded, never emailed. The
   `.gitignore` is written before any other file in this repo.
2. API processing of transcript text (extraction) under Anthropic's commercial
   terms is permitted; only the **anonymized canon** is ever persisted outside
   the machine.
3. The canon uses **initials only**. No full names, no employer names, no
   identifying details in the quote's context field. If a quote itself contains
   a third party's name, the reviewer redacts to an initial during review
   (`[his wife K—]` style) — the *only* permitted edit to a verbatim quote,
   and it is always visibly bracketed.
4. Any output generated *from* the canon for external use (marketing, site,
   book) strips identifying detail. **Named attribution only with that man's
   explicit recorded yes.**
5. The men are told on intro calls: recorded to build from, anonymized outside
   the squad, named only with permission.
6. The viewer renders the canon only, behind platform access protection, with
   no write path and no transcript access.

---

## 10. Build order

1. Repo scaffold: `.gitignore` FIRST, then folders, `config.yaml`, `tags.md`
   with seed tags + definitions, empty canon files, `TAXONOMY-CHANGELOG.md`.
2. Canon model + writers: entry model → renders `their-words.md` (tag index at
   top) and `their-words.json` from one source of truth. Unit-test round-trip.
3. Roster handling (§5.2) + manifest scanner (§5.1, trigger rule §2a).
4. Extraction (§5.1 API call, owner exclusion §5.3) → `candidates/`.
5. Review CLI (§5.4) with approve/edit/kill → append, regenerate, commit.
6. Viewer (§7): static page, filters, search, copy, stats. Local test against
   a seeded canon of ~12 fake entries.
7. Vercel deployment + protection + the incognito acceptance test.
8. Taxonomy tooling (§5.5) + `add-text` (§5.6) + watcher, then polish.

Commit after each step.

---

## 11. Acceptance criteria

1. Dropping a new processed call into the upstream `output/` and running
   `ingest` produces a candidate file; nothing enters the canon.
2. `review` walks candidates one-by-one; approvals appear in **both** canon
   files with sequential `TW-` ids, correct initials, correct context derived
   from `classification`; a dated commit is created.
3. `git push` → the Vercel URL shows the new entries within ~a minute.
4. Filters, counts, search, and copy all work on desktop and phone.
5. Incognito test (§7) passes: protected URL, no quotes without auth.
6. `git ls-files` shows **no** roster, candidates, state, transcripts, or
   `.env` at any point in history.
7. The owner's words never appear as entries (spot-check a squad-call ingest).

## 12. Non-goals

No hand-rolled auth. No public access. No editing/approving via the web — the
canon changes only through the local review CLI. No paraphrase, summarization,
or "cleanup" of quotes anywhere. No uploading transcripts to any service beyond
the extraction API call. No analytics/tracking scripts in the viewer.
