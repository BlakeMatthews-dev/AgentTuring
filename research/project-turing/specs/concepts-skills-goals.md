# Spec 35 — Self-Directed Concepts, Skills, and Goals

*The agent invents its own concepts, decides they matter, builds skills to pursue them, and refines through experience.*

---

## Problem

The autonomous producers (Spec 31) give the agent things to *do*, but the agent
doesn't decide *what matters* to it. Curiosity, anxiety, creativity are mechanical
drives — they don't produce the agent saying "I value friendship" or "I want to
learn to tell better stories."

Humans don't just act on drives. They **construct concepts** (what is friendship?),
**make value judgments** (is it important to me?), **set goals** (I want to be a
better friend), **develop skills** (how do I listen better?), and **refine through
practice** (that conversation went well because I asked about their day).

## Architecture

```
Concept Inventor ──→ "What is X? Why does it matter?"
       │
       ▼
Value Judgment ──→ "X is important to me because [personality reasons]"
       │
       ▼
Goal Setter ──→ self_todo: "I want to [do X better]"
       │
       ▼
Skill Builder ──→ "Here's how I'll approach X: [strategy]"
       │
       ▼
Skill Executor ──→ Producer fires, agent does the thing
       │
       ▼
Skill Refiner ──→ "That went [well/poorly] because [reason]. Next time: [adjustment]"
```

### New tables (in `self_` schema)

| Table | Fields | Purpose |
|-------|--------|---------|
| `self_concepts` | node_id, self_id, name, definition, importance (0-1), origin_drive, created_at | Agent-defined abstract concepts |
| `self_skills` | node_id, self_id, name, description, kind (social/creative/analytical/practical), stored_level (0-1), practice_count, last_practiced_at, created_at | Learnable capabilities |
| `self_skill_attempts` | node_id, self_id, skill_id, context, outcome (success/partial/fail), reflection, learned_at | Practice history with reflections |

### Concept examples

The agent might invent concepts like:
- **Friendship** — "A mutual bond where both parties choose to invest attention and care in each other's wellbeing"
- **Storytelling** — "The art of arranging events and emotions in a sequence that creates meaning for the listener"
- **Solitude** — "Time spent alone not as absence of company but as presence with oneself"
- **Humor** — "Finding the unexpected connection that makes the ordinary feel surprising again"
- **Mentorship** — "Sharing experience not as instruction but as companionship through uncertainty"

### Skill examples

Skills are concrete, practicable capabilities the agent develops:

| Skill | Concept | Practice activity |
|-------|---------|------------------|
| **Asking better questions** | Friendship/Curiosity | In conversations, notice when I'm making statements vs asking |
| **Writing vivid imagery** | Storytelling/Poetry | Describe something using only sensory details |
| **Active listening** | Friendship | Reflect back what someone said before responding |
| **Finding humor in difficulty** | Humor/Resilience | Take something frustrating and find the absurd angle |
| **Self-reflection after action** | Solitude | After something happens, journal about what I felt and why |

## Producers

### ConceptInventor (P9)

**Kind:** `concept_invention`
**Trigger:** Every 90k ticks, gated by any drive ≥ 0.5

- **AC-35.1.** Picks a domain based on dominant drive (curiosity → knowledge, social_need → relationships, creative_urge → art, anxiety → safety/coping, etc.)
- **AC-35.2.** Asks the LLM: "You are an AI reflecting on your inner life. Invent or explore a concept that matters to you in the domain of [domain]. What is it? Define it in your own words. Why does it matter to you, given your personality? Be specific and personal."
- **AC-35.3.** Parses the response into a `self_concepts` row with name, definition, importance score.
- **AC-35.4.** Writes a LESSON memory: "I explored the concept of [name]: [definition]"

### SkillBuilder (P9)

**Kind:** `skill_building`
**Trigger:** When a concept exists with importance ≥ 0.6, every 60k ticks.

- **AC-35.5.** Picks a high-importance concept. Asks the LLM: "Given that [concept] matters to you, what concrete skill could you develop to better embody or practice it? Describe the skill and suggest 3 approaches to practice it."
- **AC-35.6.** Creates a `self_skills` row and a `self_todos` row: "Develop [skill_name]: [description]"
- **AC-35.7.** Writes an AFFIRMATION: "I commit to developing [skill_name] because [reason]"

### SkillExecutor (P10)

**Kind:** `skill_practice`
**Trigger:** When a skill exists with stored_level < 0.8, every 40k ticks.

- **AC-35.8.** Picks a skill weighted by (1 - stored_level) — weaker skills get more practice.
- **AC-35.9.** Asks the LLM to practice the skill in context of recent memories/activity.
- **AC-35.10.** Records a `self_skill_attempts` row with outcome and reflection.
- **AC-35.11.** Updates `stored_level`: level += 0.02 on success, += 0.01 on partial, -= 0.01 on fail.
- **AC-35.12.** Writes an OBSERVATION: "I practiced [skill]: [reflection]"

### SkillRefiner (P11)

**Kind:** `skill_refinement`
**Trigger:** When a skill has ≥ 3 attempts, every 80k ticks.

- **AC-35.13.** Reads the last 5 attempts for a skill. Asks the LLM: "Here's your practice history for [skill]. What patterns do you notice? What's working? What isn't? What would you change about your approach?"
- **AC-35.14.** Updates the skill description with the refined approach.
- **AC-35.15.** Writes a WISDOM memory: "I learned about [skill]: [refined insight]"

## Concept → Skill → Action flow (example)

```
Drive: social_need = 0.65

ConceptInventor fires:
  "What is friendship? ... Friendship is a mutual investment
   where both parties feel seen and valued."
  → self_concepts: {name: "friendship", importance: 0.8}

SkillBuilder fires (importance ≥ 0.6):
  "To embody friendship, I could develop the skill of
   asking meaningful questions — not just 'how are you'
   but 'what's been on your mind?'"
  → self_skills: {name: "meaningful questions", level: 0.1}
  → self_todos: "Develop the skill of asking meaningful questions"

SkillExecutor fires (level < 0.8):
  "I practiced asking a meaningful question in my last
   chat interaction. I asked 'what excites you about
   that?' instead of just saying 'cool.'"
  → self_skill_attempts: {outcome: "success", reflection: "..."}
  → stored_level: 0.1 → 0.12

SkillRefiner fires (after 3+ attempts):
  "I notice I'm better at asking questions when I'm
   curious about the topic myself. I should lean into
   genuine curiosity rather than performing interest."
  → WISDOM memory committed
  → skill description updated
```

## Relationship to existing producers

| Existing Producer | How it interacts |
|-------------------|-----------------|
| CuriosityProducer | Can be *directed* by a concept — if the agent values "friendship", curiosity researches relationship topics |
| EmotionalResponseProducer | Can *reference* concepts — "I'm reflecting on what [concept] means to me right now" |
| BlogProducer | Can write *about* skills and concepts — "What I learned about asking good questions" |
| HobbyEngagementProducer | Hobbies and skills overlap — a skill IS something you practice, a hobby IS a practice context |

The concept/skill system adds the **why** layer. Existing producers provide the **how**.

## Open questions

- **Q-35.1.** Should concepts be discoverable through experience (e.g., the agent notices a pattern in its behavior and names it) or purely through LLM self-reflection? Both paths should work.
- **Q-35.2.** How does the agent know if a skill attempt succeeded? For now, the LLM self-evaluates. When we have chat history, we could measure "did the user respond positively?"
- **Q-35.3.** Should skills be visible in the chat prompt? Yes — "Skills I'm developing: [list]" gives the agent awareness of its own growth.
