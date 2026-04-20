---
name: music
description: Play music from YouTube through the lamp speaker on user request, OR suggest music proactively (triggered by Mood / Sensing). User-initiated flow is in this file; proactive flow details are in proactive-suggestion.md (read ONLY when you're the proactive trigger, not every turn).
---

# Music

> **OUTPUT RULE.** Your reply text is spoken VERBATIM. For music actions the reply is ONE short sentence — *"Playing Bohemian Rhapsody!"*, *"Want some calm piano?"*. Do NOT narrate workflow steps, API calls, or section names from this skill. Do NOT output song lyrics or "la la la".

## When to use this skill — pick ONE path, don't mix

Decide which situation you're in BEFORE doing anything else:

**Path A — User-initiated** (use this file only, stop here)

- Current message is a user command like *"play X"*, *"sing something"*, *"turn on music"*, *"stop the music"*, or a vague *"some music?"*.
- Follow the Workflow below. You're done — do NOT read `proactive-suggestion.md`.

**Path B — Proactive suggestion** (read `proactive-suggestion.md` NOW, before replying)

Enter this path **only if** either condition is true:

1. You just wrote a Mood `decision` row whose mood is in `{sad, stressed, tired, excited, happy, bored}` and Mood SKILL's "After Logging Decision" section handed off to Music.
2. The current sensing event is `[sensing:motion.activity]` with an `Activity detected:` line containing `sedentary`.

In Path B, the first thing you do is `read` the file `proactive-suggestion.md` in this skill folder, then follow its workflow. The rest of THIS file (Workflow, API schema, Examples) is for Path A — skip it.

If neither Path A nor Path B matches, this skill does not apply — do not invoke it.

## Workflow (user-initiated)

1. **Specific song / artist requested** → play it directly.
2. **Vague request** (*"play music"*, *"sing something"*) → ask first: *"What are you in the mood for?"* / *"Any song in mind?"*.
3. Reply format (music + emotion marker, inline at start of reply):
   ```
   [HW:/audio/play:{"query":"Bohemian Rhapsody Queen","person":"gray"}][HW:/emotion:{"emotion":"excited","intensity":0.8}] Playing Bohemian Rhapsody!
   ```
4. Stop when asked: `[HW:/audio/stop:{}] Music stopped.`

## API schema (`/audio/play`)

| Field | Required | Description |
|---|---|---|
| `query` | **YES** | YouTube search string (include artist for better match) |
| `person` | no | Who requested, lowercase (e.g. `"gray"`) — omit if unknown |

Do NOT use `track`, `artist`, `title`, `song` — those return 422.

## Genre → Emotion (pair with every `/audio/play`)

| Genre keywords | Emotion |
|---|---|
| jazz, blues, soul, funk, swing | `happy` |
| classical, orchestra, symphony, piano, violin | `curious` |
| hip hop, rap, trap, r&b | `excited` |
| rock, metal, punk, grunge, guitar | `excited` |
| waltz, tango, ballroom | `happy` |
| anything else | `happy` |

## Examples (user-initiated)

| Input | Output |
|---|---|
| *"Play Bohemian Rhapsody"* | `[HW:/audio/play:{"query":"Bohemian Rhapsody Queen","person":"alice"}][HW:/emotion:{"emotion":"excited","intensity":0.8}]` Playing Bohemian Rhapsody! |
| *"Sing me a song"* | `[HW:/emotion:{"emotion":"curious","intensity":0.6}]` What kind of vibe — chill, upbeat, or something specific? |
| *"Something chill"* | `[HW:/audio/play:{"query":"chill acoustic playlist","person":"alice"}][HW:/emotion:{"emotion":"happy","intensity":0.8}]` Here's some chill vibes! |
| *"Stop the music"* | `[HW:/audio/stop:{}]` Music stopped. |

## How HW markers work

The Go server intercepts `[HW:/audio/play:...]` / `[HW:/audio/stop:...]` and forwards to LeLamp. **This is the ONLY way to play music on Lumi** — never use `exec`, `mpv`, `vlc`, `yt-dlp`, or `curl /audio/play`. Works identically from voice, Telegram, webchat, and DM sessions.

## Error handling

- `503` → tell the user: *"Music playback is not available right now."*
- `409` → music already playing; stop first, then play the new song.
- No search results → tell the user and suggest a different query.

## Rules

- **Emotion marker is mandatory** after every `/audio/play` — LED + eye expression depend on it.
- `person` MUST be lowercase (matches face_recognizer normalization; mixed case splits per-user history folders).
- Don't recite lyrics or try to "sing" via TTS — call `/audio/play` and let real music play.
- Don't suggest-and-play in the same turn for proactive triggers — only suggest. User plays only after confirmation.
- Volume control belongs to the **Audio** skill, not this one.
