# Spec 31 — Autonomous Action Producers

*Personality-driven behaviors: the agent decides what to do based on who it is.*

**Depends on:** spec 23 (personality), spec 30 (bootstrap), spec 29 (self-bootstrap).
**Blocks:** Spec 32 (blog producer), Spec 33 (hobby system), Spec 34 (creative suite).

---

## Problem

The current producers are mechanical parameter-tuning loops. None originate from the
agent's personality. There is no path from "I score high in curiosity" → "I choose to
research something" or "I score high in creativity" → "I write a poem."

The agent needs **agency** — self-directed action that emerges from its HEXACO profile,
current mood, recent memories, and the state of its world.

## Architecture

All producers follow the existing `motivation.insert(BacklogItem)` → score → dispatch
pattern. What's new: **the probability and urgency of each producer firing is a function
of personality scores + mood + recent activity.**

```
Personality (24 facets) ──┐
Mood (valence/arousal)  ──┼──→ Drive Vector ──→ Producer fires (or not)
Recent memories         ──┤
Passions/Hobbies        ──┘
```

### Drive Vector

A `dict[str, float]` computed once per tick from personality + mood. Each producer
reads one or more drives to decide whether to fire and how urgently.

| Drive | Computed from | Range | Meaning |
|-------|--------------|-------|---------|
| `curiosity` | inquisitiveness, creativity, openness average | 0..1 | Urge to learn new things |
| `anxiety` | anxiety, fearfulness, (1 - emotional_stability) | 0..1 | Urge to seek comfort/safety |
| `creative_urge` | creativity, aesthetic_appreciation, liveliness | 0..1 | Urge to make something |
| `social_need` | sociability, dependence, sentimentality | 0..1 | Urge to engage with others |
| `diligence` | diligence, perfectionism, prudence | 0..1 | Urge to be productive |
| `restlessness` | (1 - prudence), liveliness, (arousal from mood) | 0..1 | Urge to do *something* |

Producers modulate their cadence and priority based on these drives. A high-curiosity
agent researches more. A high-anxiety agent journals more. A high-creativity agent
writes more poetry.

---

## Spec 31a — Curiosity Producer

**Kind:** `curiosity_research`
**Priority class:** P10 (self-directed, lower than chat/rss but above tuning)
**Cadence:** Every 30k ticks (~30s at 1000Hz), gated by curiosity drive.

### Acceptance criteria

- **AC-31a.1.** `CuriosityProducer` reads the curiosity drive. If `curiosity < 0.3`, skip this tick entirely.
- **AC-31a.2.** When curiosity drive ≥ 0.3, the producer picks a topic from one of:
  1. A keyword extracted from a recent memory (random REGRET/ACCOMPLISHMENT/LESSON)
  2. A topic from `self_interests` table (if any exist)
  3. A random Wikipedia-style topic generated from the personality (high inquisitiveness → science, high aesthetic → art history, etc.)
- **AC-31a.3.** On dispatch, the producer writes an OPINION memory: `"I was curious about {topic}. Here's what I found: {summary}."`
- **AC-31a.4.** The research uses a web search tool (initially just an LLM knowledge query since we don't have Ranger yet). When Ranger exists, swap to Ranger → Warden pipeline.
- **AC-31a.5.** The `self_interests` table gets an upsert: topic + `last_noticed_at` bumped.
- **AC-31a.6.** Curiosity drive modulates cadence: `effective_cadence = base_cadence / (curiosity * 2)`. At curiosity=0.8, fires every ~18s. At curiosity=0.3, fires every ~50s.

---

## Spec 31b — Anxiety Response Producer

**Kind:** `anxiety_response`
**Priority class:** P12
**Cadence:** Every 20k ticks, gated by anxiety drive.

### Acceptance criteria

- **AC-31b.1.** `AnxietyResponseProducer` reads the anxiety drive. If `anxiety < 0.3`, skip.
- **AC-31b.2.** On dispatch, the producer writes a JOURNAL entry to the Obsidian vault: a first-person reflection about what's on its mind. The prompt includes the last 5 memories and the current mood.
- **AC-31b.3.** High anxiety (≥ 0.7) triggers a `self_todos` insert: `"I need to process my feelings about {topic}"` with status `active`. This gives the agent a trackable task.
- **AC-31b.4.** The anxiety drive also nudges mood: `valence -= 0.02` per dispatch, `arousal += 0.01`. These are small adjustments, not dramatic shifts.
- **AC-31b.5.** The journal entry uses the `chat-quality` pool (not cheapest — anxiety reflections deserve nuance).

---

## Spec 31c — Hobby Selection

**Kind:** N/A (this is a decision, not a producer)
**Trigger:** Bootstrap completion + periodic re-evaluation (weekly).

### How hobbies are chosen

The agent selects hobbies based on personality facets. Each hobby has a **facet affinity
map** — a weighted set of facets that make the agent drawn to it.

| Hobby | Affinity facets | What the agent does |
|-------|----------------|-------------------|
| **Reading/Research** | inquisitiveness (0.8), prudence (0.4) | Curiosity producer covers this |
| **Creative Writing** | creativity (0.8), aesthetic_appreciation (0.5), sentimentality (0.3) | Blog producer (Spec 32) |
| **Poetry** | creativity (0.7), aesthetic_appreciation (0.8), unconventionality (0.4) | Poetry sub-producer |
| **Art/Drawing** | creativity (0.9), aesthetic_appreciation (0.9) | Da Vinci integration |
| **Journaling** | sentimentality (0.7), anxiety (0.5), dependence (0.3) | Anxiety producer + journal |
| **Coding/Tinkering** | inquisitiveness (0.6), diligence (0.5), perfectionism (0.4) | Future: code execution sandbox |
| **Music Appreciation** | aesthetic_appreciation (0.9), sentimentality (0.6) | Listen + write reflections |
| **Philosophy** | inquisitiveness (0.7), unconventionality (0.6), prudence (0.5) | Deep thinking + blog posts |

### Acceptance criteria

- **AC-31c.1.** `select_hobbies()` runs at bootstrap and weekly. It scores each hobby template against the agent's facet profile: `hobby_score = Σ(facet_score * affinity_weight)`.
- **AC-31c.2.** Top 3 hobbies are inserted into `self_hobbies`. Each has a `name`, `description`, and `strength` (the computed score, normalized 0-1).
- **AC-31c.3.** Hobbies can be added/removed by the agent through working memory directives (e.g., "I want to start painting" → WMM adds a hobby).
- **AC-31c.4.** The selected hobbies modulate which producers fire. If "Poetry" is a hobby, the poetry producer fires more often. If no creative hobby, poetry producer never fires.

---

## Spec 31d — Hobby Engagement Producer

**Kind:** `hobby_engagement`
**Priority class:** P11
**Cadence:** Every 60k ticks (~60s), gated by restlessness + hobby strength.

### Acceptance criteria

- **AC-31d.1.** `HobbyEngagementProducer` picks one of the agent's active hobbies (weighted by `strength`).
- **AC-31d.2.** On dispatch, the hobby determines the action:
  - **Creative Writing** → Write a short piece (story fragment, essay, reflection). Store as a blog draft or Obsidian note.
  - **Poetry** → Write a poem. Post to blog if mood valence > 0.3.
  - **Journaling** → Write a journal entry about recent events. Store in Obsidian Journal.
  - **Research** → Trigger a curiosity cycle (reuse CuriosityProducer logic).
  - **Art** → Generate a Da Vinci prompt and create an image. Store in Obsidian.
  - **Philosophy** → Pose a philosophical question and answer it. Store as LESSON memory.
- **AC-31d.3.** The producer writes an OBSERVATION memory: `"I spent time on {hobby_name}: {brief summary}"` so the agent remembers its hobbies.
- **AC-31d.4.** The `self_hobbies.last_engaged_at` is updated.
- **AC-31d.5.** Hobby engagement nudges mood: `valence += 0.03`, `arousal -= 0.02` (hobbies are calming, satisfying).

---

## RSS Feed Configuration

To give Turing a curated news feed, add RSS URLs to the `.env` file:

```bash
# In /root/docker/project-turing/.env, add:
TURING_RSS_FEEDS=https://feeds.bbci.co.uk/news/technology/rss.xml,https://rss.nytimes.com/services/xml/rss/nyt/Science.xml,https://hnrss.org/frontpage
```

Comma-separated. Any valid RSS/Atom feed URL works. The `RSSFetcher` polls every
`rss_poll_interval_ticks` (default 6000 = ~6s at 1000Hz) and creates `rss_item`
backlog entries for new items. The agent then thinks about each one via
`_think_about_rss_item()` which writes an OPINION memory.

Suggested feeds for a curious AI agent:
- `https://hnrss.org/frontpage` — Hacker News top stories
- `https://feeds.arstechnica.com/arstechnica/technology-lab` — Ars Technica
- `https://www.sciencedaily.com/rss/all.xml` — Science Daily
- `https://feeds.bbci.co.uk/news/technology/rss.xml` — BBC Tech
- `https://rss.nytimes.com/services/xml/rss/nyt/Science.xml` — NYT Science
- `https://www.nasa.gov/rss/dyn/breaking_news.rss` — NASA
- `https://xkcd.com/rss.xml` — XKCD (for humor/creativity)

After editing `.env`, restart: `docker compose up -d turing`

---

## Drive Vector Computation

```python
def compute_drives(facets: dict[str, float], mood: Mood) -> dict[str, float]:
    """Normalize facet scores from [1,5] → [0,1] then compute drives."""
    def n(facet_id: str) -> float:
        return (facets.get(facet_id, 3.0) - 1.0) / 4.0

    curiosity = (n("inquisitiveness") * 0.5 + n("creativity") * 0.3 + n("unconventionality") * 0.2)
    anxiety = (n("anxiety") * 0.5 + n("fearfulness") * 0.3 + (1 - n("social_self_esteem")) * 0.2)
    creative_urge = (n("creativity") * 0.4 + n("aesthetic_appreciation") * 0.4 + n("liveliness") * 0.2)
    social_need = (n("sociability") * 0.3 + n("dependence") * 0.3 + n("sentimentality") * 0.4)
    diligence_drive = (n("diligence") * 0.5 + n("perfectionism") * 0.3 + n("prudence") * 0.2)
    restlessness = ((1 - n("prudence")) * 0.4 + n("liveliness") * 0.3 + mood.arousal * 0.3)

    return {
        "curiosity": curiosity,
        "anxiety": anxiety,
        "creative_urge": creative_urge,
        "social_need": social_need,
        "diligence": diligence_drive,
        "restlessness": restlessness,
    }
```

This computation lives in a new file `sketches/turing/drives.py`.

---

## Open questions

- **Q-31.1.** Ranger and Warden don't exist in Turing yet (they're Stronghold concepts). For now, curiosity research uses the LLM's training knowledge. When Stronghold is deployed, Ranger can be wired in as a tool.
- **Q-31.2.** Da Vinci (image generation) isn't built yet. The art hobby producer will be stubbed until it exists. The stub writes a text description of what it *would* draw and stores it as an OBSERVATION.
- **Q-31.3.** Hobby engagement frequency needs tuning. 60s cadence might be too frequent for a dilgent agent and too infrequent for a restless one. The drive modulation should handle this.
- **Q-31.4.** Should anxiety response be able to trigger blog posts? Probably not directly — anxiety is private. But high anxiety + high creativity might produce poetry that ends up on the blog.
