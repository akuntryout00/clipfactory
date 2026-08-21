# Providers & models

Everything that talks to an external AI service sits behind a small protocol so it can be swapped or extended without touching business logic.

| Role | Protocol | Implementations | Selected by |
|---|---|---|---|
| LLM (scripts, scene plans, ranking, enrichment, clip analysis) | `app/llm/base.py::LLMProvider` | `openai_provider.OpenAIProvider`, `fake.FakeLLM` | `LLM_PROVIDER=openai|fake`, `OPENAI_MODEL` |
| Voice (TTS + word timestamps) | `app/voice/base.py::VoiceProvider` | `elevenlabs.ElevenLabsVoice`, `fake.FakeVoice` | `VOICE_PROVIDER=elevenlabs|fake`, persona `voice` block |
| AI Lab storyboard planner | `app/lab/providers.py::Planner` | `OpenAIPlanner`, `FakePlanner` | `LAB_PLANNER` |
| AI Lab keyframe images | `ImageGen` | `OpenAIImageGen` (`images.generate` / `images.edit` with previous frame), `FakeImageGen` | `LAB_IMAGE_PROVIDER`, `OPENAI_IMAGE_MODEL`, `OPENAI_IMAGE_QUALITY` |
| AI Lab video | `VideoGen` | `OmniVideoGen` (`omni`), `GoogleVideoGen` (`veo`), `FalVideoGen` (`fal:<key>`), `FakeVideoGen` | per video (`video_provider`), default `LAB_VIDEO_PROVIDER` |

## Video providers (AI Lab)

| id | model | how frames are used | clip length | edit | price hint |
|---|---|---|---|---|---|
| `omni` | `gemini-omni-flash-preview` (Interactions API) | keyframe N = literal `<FIRST_FRAME>`, keyframe N+1 = `<IMAGE_REF_0>` end reference (no true interpolation) | ≤10 s | conversational (`previous_interaction_id`) | ~$0.10/s |
| `veo` | `veo-3.1-fast-generate-preview` (generate_videos) | true first + last frame | ≤8 s | – | ~$0.15/s |
| `fal:minimax-h3` | `minimax/h3/image-to-video` | `image_url` + `end_image_url` | 5–15 s | – | ~$0.26/s |
| `fal:seedance-2.0` / `-fast` / `-1080p` | `bytedance/seedance-2.0[/fast]/image-to-video` | `image_url` + `end_image_url`, `aspect_ratio 9:16` | 4–15 s | – | ~$0.30 / 0.24 / 0.68 /s |
| `fal:seedance-2.5` | `bytedance/seedance-2.5/image-to-video` | same, single shot up to 30 s | 4–30 s | – | ~$0.47/s |
| `fal:kling-3.0-std` / `-pro` | `fal-ai/kling-video/v3/{standard,pro}/image-to-video` | `start_image_url` + `end_image_url` | 3–15 s | – | ~$0.08 / 0.42 /s |

All outputs are normalised to 1080×1920 / 30 fps / H.264 + AAC before concatenation. Prices are list prices at the time of writing (see `FAL_MODELS[...]["price_per_second"]` and `list_video_providers()`); update them when providers change pricing.

## Adding a fal.ai model (≈10 lines)
1. Look up the endpoint's input schema: `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<endpoint>`.
2. Add an entry to `FAL_MODELS` in `app/lab/providers.py`:
   ```python
   "my-model": {
       "endpoint": "vendor/model/image-to-video", "label": "My Model", "max_seconds": 10, "min_seconds": 4,
       "price_hint": "~$0.20/s", "price_per_second": 0.20, "note": "first+last frame, audio",
       "args": lambda first, last, prompt, sec: {"prompt": prompt, "image_url": first, "end_image_url": last,
                                                 "aspect_ratio": "9:16", "duration": str(int(sec))},
   },
   ```
3. It appears automatically in `GET /lab/providers`, the UI dropdown and `estimate`. Add a row to `tests/test_lab_fal.py::test_fal_animate_builds_arguments_and_normalizes` for the argument mapping.

## Adding a non-fal video provider
Implement the `VideoGen` protocol (`name`, `model`, `max_seconds`, `min_seconds`, `last_ref`, `animate(first, last, prompt, seconds, out_path) -> Path`, `edit(...)` or raise `NotImplementedError`), write the clip to `out_path` through `_normalize_segment`, register it in `get_video_gen()` and `list_video_providers()`.

## Adding an LLM or voice provider
Implement `LLMProvider` (all methods return pydantic models from `app/schemas/pipeline.py`) or `VoiceProvider` (`synthesize(text, voice, out_path) -> VoiceResult` with word timings — if the vendor has no alignment, use `voice/alignment.py::synthetic_words`) and register in the `get_*` factory. Keep prompts in `app/llm/prompts.py`.

## Keys & costs
Keys are read from `.env` (see `.env.example`). The System page and `clipfactory doctor` show what is configured. Every provider call costs money; the AI Lab shows an estimate before you start, the content factory logs each stage.
