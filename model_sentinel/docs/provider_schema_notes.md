# Provider Schema Notes

This document records a public, unauthenticated endpoint review performed on
2026-07-26. It captures schema facts useful to Model Sentinel's provider
profiles without checking raw payloads into this public repository.

The authenticated Abacus.AI and OpenCode Zen responses have not been
validated. Account-specific fields, models, prices, or envelope differences
may exist. Treat these notes as a starting point for future profiles, not as an
authenticated API contract.

## Summary

| Provider | Public endpoint shape | Model record shape | Current profile |
|---|---|---|---|
| OpenRouter | Object with model list in `data`; the observed response also exposed root metadata such as `total_count` and `links` | Rich nested records with pricing, capabilities, limits, defaults, and optional benchmark/reasoning data | Registered `openrouter` profile |
| Abacus.AI | Object with model list in `data` | Flat records with many model-type-specific `*_rate` fields | Generic fallback; dedicated profile deferred |
| OpenCode Zen | OpenAI-style object with model list in `data` | Minimal records: `id`, `object`, `created`, `owned_by` | Generic fallback |

## OpenRouter

Endpoint reviewed: `https://openrouter.ai/api/v1/models`.

The OpenRouter profile deliberately pins `envelope_keys=("data",)` and owns
the provider vocabulary currently used for field labels, known boolean paths,
conditional-pricing identity, and default report-detail policy.

Observed top-level model fields included:

- `id`, `canonical_slug`, `hugging_face_id`, `name`, `created`, `description`
- `context_length`, `architecture`, `top_provider`, `per_request_limits`
- `pricing`, `supported_parameters`, `default_parameters`, `supported_voices`
- `knowledge_cutoff`, `expiration_date`, `links`
- optional `benchmarks` and `reasoning`

Nested pricing values were string-encoded per-token amounts for the common
token-price leaves. The registered OpenRouter rules explicitly display
`prompt`, `completion`, `internal_reasoning`, `input_cache_read`, and
`input_cache_write` per million tokens. They also declare `web_search` per
1,000 searches, `request` per request, and `image` per image. Unknown monetary
leaves display with `/unit unknown` and are excluded from token snapshot
columns and absolute token-rate comparisons.

## Abacus.AI

Endpoint reviewed: `https://routellm.abacus.ai/v1/models`.

The capture contained 146 models across four `model_type` values:
`text_generation`, `image_generation`, `audio_generation`, and
`video_generation`.

Common identity, capability, and limit fields included:

- `id`, `name`, `display_name`, `description`, `model_type`
- `context_length`, `max_completion_tokens`
- `input_modalities`, `output_modalities`, `api_formats`
- `agentic`, `computer_use`, `featured`, `thinking`, `top_model`
- `default_hd`, `default_standard`, `high_res_hd`, `high_res_standard`, `unit`

Observed rate fields included:

- Token/text/audio/image/video families: `input_token_rate`,
  `output_token_rate`, `cached_input_token_rate`, `audio_token_rate`,
  `token_rate`, `input_rate`, `output_rate`, `text_input_rate`,
  `text_output_rate`, `audio_rate`, `image_input_rate`, `image_output_rate`,
  `video_input_rate`, and `video_output_rate`.
- General or mode-specific rates: `rate`, `edit_rate`, `fast_rate`,
  `standard_rate`, `pro_rate`, `relax_rate`, `max_rate`, `grounding_rate`,
  `additional_image_rate`, `pro_audio_rate`, `standard_audio_rate`,
  `BALANCED_rate`, `QUALITY_rate`, `TURBO_rate`, `v6_turbo_rate`, and
  `v7_turbo_rate`.
- Resolution/duration variants: `2k_rate`, `4k_rate`, `8k_rate`, `10k_rate`,
  `_1k_rate`, `_2k_rate`, `_480p_rate`, `_480p_fast_rate`,
  `_580p_fast_rate`, `_720p_rate`, `_720p_fast_rate`, `_1080p_rate`,
  `fast_480p_rate`, `fast_720p_rate`, `fast_1080p_rate`,
  `standard_480p_rate`, `standard_720p_rate`, `standard_1080p_rate`,
  `_5_sec_rate`, `_5_sec_pro_rate`, `_5_sec_rate_pro`, `_5_sec_rate_std`,
  `_5_sec_standard_rate`, `_6_sec_rate`, `_6_sec_pro_rate`,
  `_6_sec_standard_rate`, `_7_sec_rate`, `_8_sec_rate`,
  `_8_sec_rate_fast_audio`, `_8_sec_rate_fast_no_audio`,
  `_8_sec_rate_standard_audio`, `_8_sec_rate_standard_no_audio`,
  `_10_sec_rate`, `_10_sec_pro_rate`, `_10_sec_rate_pro`,
  `_10_sec_rate_std`, and `_10_sec_standard_rate`.

Typing is not uniform. Many token rates are strings, while several media-rate
fields are numbers; some individual fields use both JSON number and string
values across models (including `_480p_rate`, `_720p_rate`,
`image_input_rate`, `pro_audio_rate`, `pro_rate`, `rate`, and
`standard_rate`).

The public token rates are per-token: for example, a value shaped like
`"0.000003"` corresponds to roughly $3 per million tokens. Media prices use
different units such as per image, second, or clip, and one observed model
declared `unit: "megapixel"`. Consequently, no single provider-wide
multiplier/divisor can normalize the full Abacus schema correctly.

The current `MULTIPLIER=1` template value is retained to avoid silently
changing seeded behavior, but it is known to be wrong for Abacus token rates.
A correct Abacus profile needs a validated mapping from its authenticated
fields to the existing per-field pricing-rule mechanism. Until that response
is validated and a dedicated profile is registered, Abacus uses the generic
profile and healthcheck reports the fallback.

## OpenCode Zen

Endpoint reviewed: `https://opencode.ai/zen/v1/models`.

The public response used an OpenAI-style `data` envelope. Each observed record
contained only `id`, `object`, `created`, and `owned_by`; no pricing fields were
present. The generic profile already accepts the envelope and normalizes the
shared identity/timestamp fields, so a dedicated profile would add no current
behavior. Confirm the authenticated schema before registering the kind.

## Deferred Profile Work

- Register Abacus per-field pricing rules and unit labels after validating its
  authenticated response.
- Validate authenticated Abacus and OpenCode Zen payloads against these public
  observations.
- Confirm whether OpenCode ever exposes pricing or richer capability metadata.
