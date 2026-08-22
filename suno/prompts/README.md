# Suno prompt library — D&D ambience

One file per category in this folder. Category names match the playlist/folder names used by the downloader (`sunder.py`).

Roughly 2,300 ready-to-paste Style prompts for generating a D&D ambience library on Suno — 10 unique versions per category and intensity level (I–III), across 84 categories. Original library folders are listed first; expansion categories follow. Name each Suno playlist like the target folder ("Boss III", "Feast II").

## Workflow

1. **Use Custom mode.** Paste one prompt into the **Style** field. Suno accepts ~1000 characters but weights the first ~200 most heavily — every prompt here is short enough that all of it counts.
2. **Toggle Instrumental ON.** For extra safety against v5.5 "vocal ghosting" (faint hummed melodies), put `[Instrumental]` at the start of the Lyrics field and `[No Vocals]` at the end.
3. **Lyrics field tags by level:**
   - Level I: `[Instrumental] [Sustained] [No Vocals]` — pure atmospheric continuity, almost no development.
   - Level II: `[Instrumental] [Minimal Variation] [No Vocals]` — subtle textural movement.
   - Level III: `[Instrumental] [No Vocals]` — let Suno structure it freely.
4. **Exclude Styles (Advanced mode):** `pop, EDM, trap, hip hop, rock, rap, singing` — prevents genre bleed. Remove `singing` for tracks that call for wordless choir or vocalise (Boss III, Ethereal, Victory III, some finales).
5. **Within a folder, prompts share a palette.** All 10 versions of a level keep the category's core instruments, so the folder stays cohesive while each version lands differently. Each run produces 2 takes; rerun any version you like for more of that exact flavor.
6. **Playlist naming:** name each Suno playlist exactly like the target folder ("Boss III", "Feast II"). Avoid creating two playlists with the same name — the downloader resolves collisions by suffixing the folder with the playlist id (that is where folders like `Boss III [159305e1]` come from).
7. **Looping (mainly Level I):** the prompts already ask for "steady texture with no ending"; avoid adding words like climax, finale, or triumphant ending. Crossfade the first and last few seconds in an editor to hide the loop seam.

**Troubleshooting:** if a beat creeps into a Level I track, move `no drums, no percussion` to the very front of the style field and regenerate. If a track sounds generic, the prompt is probably overloaded — Suno blurs past ~3 instruments and ~2 moods.

## Prompt formula

```text
<genre/subgenre>, <1-2 moods>, <2-3 core instruments>, <tempo>, <scene cue>, <negatives>
```

Intensity ladder — intensity is the intensification of the category itself, not a loudness or importance setting. Each level is relative to the category's own register: a calm category's III is still calm, just fuller, quicker, and brighter than its I. The category keeps its instruments (sonic identity) across levels; what changes is energy, density, and how far the mood leans toward its own peak.

| Level | Meaning within the category | Typical change from the level below |
|---|---|---|
| I | The category at its quietest and slowest — the seed of the mood | sparsest arrangement, slowest tempo the mood allows |
| II | The category in motion — the mood fully stated | clear melody and movement, medium energy for that category |
| III | The culmination — the category at its own full intensity | fastest, fullest, most dramatic version of that same mood |

Arc examples — the same I–III means different things per category:

- Boss: I slow suspense and thrill before the fight → II the epic battle underway → III the culmination, super fast and huge.
- Happy: I content and lazy → II cheerful and social → III jubilant festival — never leaves the positive register.
- Night: I starlit stillness → II dreamy nocturne → III a majestic night at full scale — still night, never combat.
- Feast: I mellow candlelit inn → II lively feast → III rowdy dance at full tilt.

Tempo numbers in the prompts are therefore per-category, not global — a calm category's III may sit at 85 BPM while Boss III runs at 150.

How the 10 versions differ while staying in-folder: each rotates the lead instrument within the category palette, changes the scene cue, shifts the mood within the same emotional family, spreads the tempo across the level's band, and occasionally changes meter or texture (a waltz, a solo-led piece, a drone-based bed). Negatives by type: pure ambience ends with `no vocals, no drums, no percussion`; melodic but drumless tracks end with `instrumental, no singing, no drums`; percussion-driven tracks end with `no lyrics, no singing`; choir tracks say `wordless choir` and `no lyrics` (never `no vocals`, which would fight the choir).

## Categories

**Original library** (27):

- [Ancient Discovery](ancient-discovery.md)
- [Aqua](aqua.md)
- [Boss](boss.md)
- [Combat](combat.md)
- [Dark and Creepy](dark-and-creepy.md)
- [Defeat](defeat.md)
- [Ethereal](ethereal.md)
- [Exploration](exploration.md)
- [Exploration Above Ground](exploration-above-ground.md)
- [Exploration Underground](exploration-underground.md)
- [Feast](feast.md)
- [Forest](forest.md)
- [Forest Swamp Combat](forest-swamp-combat.md)
- [Forest Tunes](forest-tunes.md)
- [Goofy](goofy.md)
- [Happy](happy.md)
- [Melancholy](melancholy.md)
- [Morning](morning.md)
- [Mystery](mystery.md)
- [Night](night.md)
- [Reading](reading.md)
- [Sad](sad.md)
- [Secret Magic](secret-magic.md)
- [Sneaking](sneaking.md)
- [Spooky](spooky.md)
- [Swamp](swamp.md)
- [Victory](victory.md)

**Expansion** (57): Fifty-seven additional categories, alphabetized. Same rules as above; these folders do not exist yet, so create each Suno playlist with the exact category name (plus level, e.g. "Chase II") before generating. Each identity line states the category's intensity arc — what I, II, and III mean for that specific mood.

- [Bazaar](bazaar.md)
- [Beast Hunt](beast-hunt.md)
- [Betrayal](betrayal.md)
- [Camp](camp.md)
- [Character Themes](character-themes.md)
- [Chase](chase.md)
- [City](city.md)
- [Clockwork](clockwork.md)
- [Countdown](countdown.md)
- [Court](court.md)
- [Desert](desert.md)
- [Docks](docks.md)
- [Dragon Presence](dragon-presence.md)
- [Dreamscape](dreamscape.md)
- [Dusk](dusk.md)
- [Dwarven Halls](dwarven-halls.md)
- [Eclipse](eclipse.md)
- [Eldritch](eldritch.md)
- [Elven Court](elven-court.md)
- [Epilogue](epilogue.md)
- [Fey Mischief](fey-mischief.md)
- [Forge](forge.md)
- [Gambling Den](gambling-den.md)
- [Gentle Rain](gentle-rain.md)
- [Hope](hope.md)
- [Infernal](infernal.md)
- [Intermission](intermission.md)
- [Jungle](jungle.md)
- [Last Stand](last-stand.md)
- [Madness](madness.md)
- [Main Theme](main-theme.md)
- [Mountain](mountain.md)
- [Orcish War Camp](orcish-war-camp.md)
- [Pirates](pirates.md)
- [Prison](prison.md)
- [Prophecy](prophecy.md)
- [Puzzle](puzzle.md)
- [Rally](rally.md)
- [Recap](recap.md)
- [Revelation](revelation.md)
- [Ritual](ritual.md)
- [Romance](romance.md)
- [Sacred](sacred.md)
- [Sailing](sailing.md)
- [Sewers](sewers.md)
- [Shadowfell](shadowfell.md)
- [Siege](siege.md)
- [Storm](storm.md)
- [Tension](tension.md)
- [Thieves' Guild](thieves-guild.md)
- [Trial](trial.md)
- [Undead Legion](undead-legion.md)
- [Underdark](underdark.md)
- [Villain Theme](villain-theme.md)
- [Volcanic](volcanic.md)
- [War March](war-march.md)
- [Winter](winter.md)

