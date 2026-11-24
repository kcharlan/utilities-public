# AI model timeline: update guide

How to add releases to `ai-model-timeline.html` and decide how prominently each one shows. Follow it on every update run.

Store levels in `ai_model_timeline_levels.json` beside this guide.

## What gets a row

A row records a dated event supported by a primary source from the maker. Add a row for either of these events.

- The maker releases or formally announces a distinct model, checkpoint, family or separately named variant. A formal announcement can qualify before the model is usable.
- The maker reaches a milestone for a recorded model as defined under [Folding](#folding). Use the milestone date, including when a newly verified milestone predates the current main entry.

Do not add a row for any of these. Record each one you considered in the manifest's `exclusions`, as the existing manifests do.

- A change to a service feature for an existing release, such as a priority tier, reasoning setting, alias or an API feature. For a launch that changes access to the model itself, use the stage rule under [Folding](#folding).
- An existing model appearing on another gateway, cloud or reseller.
- A price change, deprecation or retirement.
- A rumour, a prediction or a scheduled future release.
- A quantized or exported build of a checkpoint by its own maker.
- An app, tool or framework that is not itself a model. A system offered as a model endpoint under its own name does get a row.
- An event whose date no primary source establishes.

Apply this bar to new rows from any maker. Keep existing release rows.

## Levels

| `level` | Name | Shown |
| --- | --- | --- |
| 1 | Headline | By default |
| 2 | Notable | By default |
| 3 | Record | Under Everything, with the stage exception under [Folding](#folding) |

## Roster

Use the `roster` array in the levels file for current membership.

A lab joins the roster when, on an update run, it has a current model in the top 25 of the intelligence index or at least 1% of OpenRouter text requests. Add the lab to `roster` before classifying new entries or applying [Promotion](#promotion).

The roster only grows. A lab that ages out of both measures stays because its earlier Headline rows depend on it. The initial roster also retains curated platform companies for their reach.

## Rules

Apply [Folding](#folding) before classifying a row. For a main entry without a transferred classification, the first rule that fits decides the level.

1. **Announced with nothing usable is level 3** until something can be used or downloaded.
2. **A current model in the top five of the intelligence index is level 1.** Apply [Roster](#roster) to its lab first.
3. **Roster labs.**
   - The lab's new top general model is level 1.
   - A mid or small model in its main line is level 2.
   - An open-weight general model in its main line is level 2.
   - Its lead model in image, video, real-time voice, music, world models and robotics, coding, science or cyber is level 2 when it is a new numbered version of a line already in the timeline, or the lab's first model in that field. Its first public decision model also qualifies.
4. **Other roster releases are level 2 if they pass an evidence test and level 3 otherwise.** These include the following.
   - Support classes such as transcription, text-to-speech, embeddings, rerankers, document parsing, translation, classifiers and utilities.
   - Releases outside the lab's main line, such as research checkpoints and families from side teams.
   - Legal, medical and life-science configurations of an existing model.
   - A row whose only event is a documentation or catalogue listing.
5. **For other labs, use level 2 when the model passes an evidence test or is the first public model of a new kind.** Otherwise use level 3.

## Evidence tests

Apply these tests where the [Rules](#rules) call for evidence. Passing one qualifies the model for level 2. Write the independent evidence in the entry's `evidence`.

| Test | Bar |
| --- | --- |
| Intelligence index | Among the top 30 current models. |
| Usage | Top 20 text models by monthly tokens on OpenRouter, or top three in an OpenRouter category. |
| Arena or benchmark board | Top ten on an independent board for its field. |
| Adoption | 1,000 Hugging Face likes together with 50,000 monthly downloads; or 500,000 monthly downloads; or 1,000 GitHub stars on a repository created for the model. |
| Coverage | Two or more established technology or news outlets reporting independently of a press release. |

### Promotion

Re-check main entries below level 1 using the updated roster, excluding the [curated history](#rows-dated-before-september-2026). Apply the rules in order and promote entries that qualify for a higher level. Reassess an announcement when a later milestone makes the model usable. Record the change under [Level changes](#level-changes). Aging out of a ranking leaves the level in place.

## Folding

When one model has several rows, its earliest verified release, formal announcement or access milestone for the base model is the main entry and carries the level. Keep the current main entry if it shares that earliest date. Each folded row has level 3, `of`, `kind` and `label`, and the main entry's `field`.

| `kind` | What it is | Shown |
| --- | --- | --- |
| `stage` | A dated milestone where the original maker formally announces, releases or broadens access to the same model, including adding a public API or officially launching it on a hosted service. | Uses the main entry's level for the detail selector. The other filters apply to the stage itself. |
| `snapshot` | A dated or numbered revision of the same model. | Under Everything. |
| `variant` | A speed, size, serving or bundled variant released as its own row. A variant may be dated on or before its main entry. | Under Everything. |

- `of` holds the main entry's `model` and `date`. The lab is the row's own.
- A main entry is never itself folded. If a row would fold into a folded row, point it at that row's main entry.
- `label` is a short phrase saying what the row adds. Reuse a label from the levels file when it describes the same milestone. For a snapshot, give the version or what changed. For a variant, say how it differs.
- `reason` for a folded row is `Later stage: <label>`, `Snapshot: <label>` or `Variant: <label>`.

### When the main entry changes

Use this procedure when adding a row or correcting a row's identity or date within the same model. If the verified chronology makes an existing stage the earliest event for the base model, make that stage the main entry. An earlier snapshot gets that treatment only if the source establishes it as the base model's first release, announcement or access milestone. Classify a distinct earlier checkpoint separately. An earlier variant stays a variant.

1. Move the former main entry's level, field and reason to the new main entry. Replace the new main entry's evidence with the former main entry's evidence, or omit it if the former main entry had none. Remove `of`, `kind` and `label` from the new main entry.
2. Fold the former main entry into the new one as a `stage`. Label its actual event and replace its reason with the fold reason. Remove the transferred evidence.
3. Re-evaluate the other folded rows against the corrected identities and dates. Repoint the relationships that still qualify to the new main entry and use its field. Classify any row that no longer has a qualifying parent as a main entry under [Rules](#rules).
4. Record the stored-level change for each previously classified row that changed level, including the new and former main entries when applicable. Use [Level changes](#level-changes) for manifest keys and net changes.

## Fields

The field list is the `fields` array in the levels file. Each entry has exactly one.

| `field` | What belongs in it |
| --- | --- |
| `general` | General-purpose language and multimodal models, including reasoning models and cyber configurations of a general model. |
| `coding` | Models built for coding, computer use or agent work, and agent products released as a model. |
| `image` | Image generation and editing. |
| `video` | Video generation, including video with sound and avatars. |
| `audio` | Real-time voice, text-to-speech, transcription, speech translation, sound and music. |
| `world` | World models, robot and driving models. |
| `science` | Models for science, mathematics, weather, biology or medicine, including medical configurations. |
| `other` | Decision models, embeddings, rerankers, document parsing, text translation, classifiers, legal configurations and utilities. |

A folded row takes its main entry's field. The page reads each label from `fieldLabels` in the levels file; change a label there.

## Entry reasons

`reason` is a short phrase the page shows in the tooltip. Reuse the phrase in the levels file for the same case.

## Rows dated before September 2026

Curated main entries are identified by a `reason` starting with `Curated history`. Keep the editorial level in the levels file. It incorporates the historical folds and uses the original curation rather than the current evidence tests.

Apply the current rules to newly discovered rows, whatever their date, including the main-entry transfer rule under [Folding](#folding).

## Level changes

In a new update manifest, record each previously classified row whose stored level changed as `{model, lab, date, from, to, evidence}` in `levelChanges`. Use the row identity after that manifest's corrections and record one net change per row. `evidence` is a non-empty explanation of the promotion or fold.

## Steps for an update run

1. Read the boards listed below and the labs' announcements. A model that is new to a board is a candidate even when no announcement was seen.
2. Apply [What gets a row](#what-gets-a-row). Add verified rows and corrections to `DATA` and the new manifest. Record the exclusions.
3. If a correction changes a row's identity, update its levels entry and affected fold references. Re-evaluate the relationships under [Folding](#folding), including date order and whether rows still belong to the same lab and model. If the main entry changes within the same model, follow [When the main entry changes](#when-the-main-entry-changes). Classify a row whose correction leaves it with no qualifying parent under [Rules](#rules), and record any stored-level change under [Level changes](#level-changes). For a corrected spelling of a roster lab, update its roster label too.
4. Check the roster measures against the updated rows, then classify new rows under [Rules](#rules) and [Folding](#folding).
5. Apply [Promotion](#promotion).
6. Set `checked` in the levels file to the run date.
7. Run `node scripts/timeline-levels.cjs --write`, then `node scripts/timeline-analysis.cjs --write`.
8. Update the page's static header metadata as checked by the test "static header metadata and initial chart domain cover the dataset".
9. Run the tests in the README.

## Boards to read on every update

- Intelligence index: https://artificialanalysis.ai/leaderboards/models (ranks count the models the site marks current)
- Image, video, speech and music arenas: https://artificialanalysis.ai/image/leaderboard/text-to-image, https://artificialanalysis.ai/video/leaderboard/text-to-video, https://artificialanalysis.ai/text-to-speech/leaderboard, https://artificialanalysis.ai/music/leaderboard/instrumental
- Usage: https://openrouter.ai/rankings?view=month and its image, video, speech, decisions, transcription and embeddings tabs
- Adoption: the model's Hugging Face page or `https://huggingface.co/api/models/<org>/<model>`, and `https://api.github.com/repos/<owner>/<repo>` for a repository created for the model
- Robotics: https://research.nvidia.com/labs/srl/projects/robolab/leaderboard.html

The boards cover general models, image, video, speech and music well. They cover robotics, world models, science and document models poorly or not at all; for those, use the coverage test.

## Research leads for the next update

The November 24, 2026 research pass logged these leads. Check the current timeline for each candidate and verify qualifying new rows against a primary source.

| Model | Maker | Released | Where it ranked |
| --- | --- | --- | --- |
| Grok Imagine Image 2.0 | xAI | Aug 7, 2026 | Image arena rank 10 |
| Solar Pro 4 | Upstage | Aug 6 or 14, 2026 (sources differ) | Intelligence index score 14 |
| Wan 3.0 | Alibaba | Aug 24, 2026 | Video arena rank 1; OpenRouter video rank 3 |
| Sonic 3.6 | Cartesia | Aug 27, 2026 | Speech arena rank 5 |
| Utopai X | Utopai Studios | Sep 30, 2026 | Video arena rank 2; a post-train of MiniMax H3 |
| Kling Image 4.0 | Kuaishou | Nov 17, 2026 | Image arena rank 7 |
| JoyAI-VL-Preview | JD | Nov 17, 2026 | Intelligence index rank 27 (score 28) |

Dated milestones flagged for follow-up:

- Kuaishou Kling 4.0 general availability on October 15, 2026.
- World Labs Atlas unveiling on September 1, 2026.
- Microsoft Aion 1.0 announcement at Build on June 2, 2026.

Leads with no confirmed date: JT-4.1 Flash from China Mobile (sources give July 9 and November 11, 2026), Qwen-Audio-3.1-TTS-Plus (speech arena rank 4), HyperFlow H3 from Video Rebirth (video arena rank 5, a compressed MiniMax H3), SkyReels V4 (video arena rank 11), and FLUX 3 Max (video arena rank 7, excluded by an earlier run for lack of a dated source).

Remove an item from this section when its row is added or it is excluded.
