# PRD — TikTok Content Factory MVP

**Version:** 0.1
**Date:** 20 August 2026
**Status:** MVP
**Primary user:** Internal use
**Initial scope:** 1 TikTok account / 1 persona

---

## 1. Product Summary

TikTok Content Factory, önceden çekilmiş gerçek B-roll görüntülerini, tek bir tanımlı persona'yı, AI tarafından oluşturulan scriptleri ve ElevenLabs seslendirmesini kullanarak otomatik şekilde TikTok-ready dikey videolar üreten internal bir content generation sistemidir.

Kullanıcı sisteme temel olarak:

**Topic + Template**

verir.

Sistem otomatik olarak:

```text
Topic
  ↓
Persona
  ↓
Script + Hook
  ↓
Scene Planning
  ↓
B-roll Selection
  ↓
ElevenLabs Voice
  ↓
Voice Timing
  ↓
Text / Captions
  ↓
Video Rendering
  ↓
1080×1920 MP4
```

üretir.

MVP'nin amacı TikTok'a otomatik paylaşım yapmak veya trendleri otomatik bulmak değildir.

Başarı kriteri:

> Kullanıcı bir topic ve template seçtikten sonra minimum manuel müdahaleyle yayınlanabilecek kalitede 15–25 saniyelik TikTok videosu oluşturabilmelidir.

---

# 2. Problem

Birden fazla TikTok hesabını düzenli şekilde beslemek için yüksek miktarda video içeriğine ihtiyaç vardır.

Manuel süreçte her video için:

* fikir oluşturmak
* script yazmak
* voice-over hazırlamak
* uygun B-roll bulmak
* klipleri kesmek
* sıralamak
* text eklemek
* subtitle oluşturmak
* müzik eklemek
* render almak

gerekmektedir.

Bu workflow bir video için bile ciddi zaman harcatır ve günlük yüksek hacimli içerik üretiminde ölçeklenmez.

Buna karşılık generative video kullanarak tüm videoyu AI ile oluşturmak:

* pahalıdır,
* yavaştır,
* tutarsızdır,
* yapay görünebilir,
* creator kimliğinin devamlılığını zorlaştırır.

Çözüm olarak sistem, kullanıcının kendi çektiği gerçek görüntüleri yeniden kullanarak AI'yı **creative planning + assembly** katmanı olarak kullanacaktır.

---

# 3. Product Principle

Temel mimari prensip:

> **LLM video üretmez. LLM video planı üretir.**

AI çıktısı doğrudan MP4 değil, structured `Video JSON` olacaktır.

Video renderer bu JSON'u deterministic şekilde gerçek videoya dönüştürecektir.

```text
LLM
 ↓
Video JSON
 ↓
Renderer
 ↓
MP4
```

Bu ayrım sayesinde sistem:

* predictable,
* debug edilebilir,
* ucuz,
* hızlı,
* template-driven,
* genişletilebilir

olacaktır.

---

# 4. MVP Goals

MVP aşağıdaki workflow'u uçtan uca gerçekleştirmelidir.

### Input

```text
Persona: Young Professional
Template: Story
Topic: Stop taking meeting notes manually
Target duration: 15–20 sec
```

### Output

```text
1080 × 1920
9:16
MP4

15–25 sec

✓ B-roll
✓ voice-over
✓ dynamic captions
✓ text overlays
✓ background music
✓ basic editing
```

İdeal durumda kullanıcı videoyu izleyip doğrudan TikTok'a yükleyebilmelidir.

---

# 5. Non-Goals

Aşağıdakiler **MVP kapsamında değildir**:

* 10 TikTok hesabı
* birden fazla persona
* TikTok automatic posting
* TikTok API
* trend discovery
* competitor monitoring
* automatic topic discovery
* analytics ingestion
* performance learning
* automatic A/B testing
* autonomous content calendar
* comment monitoring
* automatic comment replies
* generative B-roll
* AI avatar
* talking-head generation
* mobile application
* complex video editor
* collaborative workflow

Bunlar MVP doğrulandıktan sonra değerlendirilecektir.

---

# 6. Primary Persona

MVP'de tek persona bulunacaktır.

## Young Professional

**Audience**

US ağırlıklı 20–30 yaş profesyoneller.

**Topics**

* productivity
* career
* networking
* AI
* useful apps
* workplace
* technology

**Tone**

* casual
* intelligent
* concise
* slightly sarcastic
* TikTok-native

**Avoid**

* corporate language
* exaggerated marketing
* fake personal stories
* excessive CTA
* hard selling
* unverifiable claims

**Language**

English — US.

Persona sistem içinde configuration olarak tutulmalıdır.

Örneğin:

```json
{
  "id": "young_professional",
  "language": "en-US",
  "audience": "US professionals aged 20-30",
  "topics": [
    "productivity",
    "career",
    "networking",
    "AI",
    "useful apps"
  ],
  "tone": [
    "casual",
    "smart",
    "concise",
    "slightly sarcastic"
  ],
  "avoid": [
    "corporate language",
    "hard selling",
    "fake personal stories",
    "unverifiable claims"
  ],
  "target_duration": 18,
  "max_duration": 25
}
```

Architecture gelecekte birden fazla persona destekleyebilecek şekilde tasarlanmalıdır ancak MVP UI'da persona seçimi gerekli değildir.

---

# 7. Asset Library

Sistem kullanıcının daha önceden çektiği B-roll videolarını kullanacaktır.

Asset kategorileri örneğin:

```text
/assets

/desk
/phone
/networking
/lifestyle
/walking
/productivity
/problem
/reaction
/product
```

Her asset'in metadata'sı bulunmalıdır.

### Asset Model

```json
{
  "id": "asset_034",
  "file": "phone/phone_scroll_01.mp4",
  "tags": [
    "phone",
    "scrolling",
    "productivity"
  ],
  "action": "scrolling_phone",
  "location": "office",
  "shot": "close",
  "mood": "neutral",
  "duration": 8.4,
  "usable_start": 1.2,
  "usable_end": 7.4,
  "quality_score": 0.9,
  "usage_count": 3,
  "last_used_at": null
}
```

---

# 8. Asset Import

MVP'de kullanıcı videoları belirlenen asset klasörüne ekleyebilmelidir.

Sistem otomatik olarak teknik metadata çıkarmalıdır:

* filename
* duration
* resolution
* orientation
* FPS

Semantic metadata ilk MVP'de manuel veya AI-assisted olabilir.

Minimum required metadata:

```text
action
location
shot
mood
tags
```

Asset kullanılmadan önce `approved=true` olmalıdır.

---

# 9. Asset Selection Engine

Video oluşturulurken sistem her scene için uygun B-roll seçmelidir.

Selection aşağıdaki faktörleri değerlendirmelidir:

### Semantic relevance

Scene ile asset ne kadar ilişkili?

### Quality

Asset'in kalite score'u.

### Freshness

Aynı asset yakın zamanda kullanıldı mı?

### Usage count

Asset gereğinden fazla kullanıldı mı?

Basit conceptual scoring:

```text
score =
semantic_relevance
× quality_score
× freshness_multiplier
```

Yakın zamanda kullanılan asset'lere penalty uygulanmalıdır.

Örneğin:

```text
used today       → strong penalty
used last 3 days → medium penalty
used last 7 days → small penalty
```

MVP'de asset library küçük olduğundan vector database zorunlu değildir.

LLM'e filtrelenmiş asset catalog verilerek doğrudan `asset_id` seçtirilebilir.

---

# 10. Template System

MVP dört video template destekleyecektir.

## Template 01 — Story

Amaç:

Narrative / educational içerik.

Structure:

```text
0–2 sec
HOOK

2–6 sec
SETUP

6–11 sec
DEVELOPMENT

11–16 sec
PAYOFF

16–20 sec
ENDING
```

Voice-over dominant olacaktır.

---

## Template 02 — List

Örneğin:

> 3 things I stopped doing to save time.

Structure:

```text
HOOK

ITEM 1

ITEM 2

ITEM 3

ENDING
```

Büyük text overlay kullanılacaktır.

---

## Template 03 — POV

Örneğin:

> POV: you spent 30 minutes doing something AI does in 10 seconds.

Structure:

```text
HOOK

PROBLEM

REALIZATION

RESULT
```

Voice-over optional olabilir.

---

## Template 04 — Problem / Solution

Ürün içeren içerikler için kullanılacaktır.

```text
HOOK
 ↓
PROBLEM
 ↓
TRANSITION
 ↓
SOLUTION
 ↓
RESULT
```

MVP'de product screen recording asset olarak kullanılabilir.

---

# 11. Template Configuration

Template'ler kod içine hard-code edilmemeli, configuration olarak tanımlanmalıdır.

Örneğin:

```json
{
  "id": "story_v1",
  "duration": {
    "min": 15,
    "target": 18,
    "max": 22
  },
  "sections": [
    {
      "type": "hook",
      "weight": 0.12
    },
    {
      "type": "setup",
      "weight": 0.25
    },
    {
      "type": "development",
      "weight": 0.33
    },
    {
      "type": "payoff",
      "weight": 0.30
    }
  ],
  "voiceover": true,
  "caption_style": "dynamic_center"
}
```

Gelecekte:

```text
story_v2
story_fast
story_product
story_cinematic
```

gibi template'ler eklenebilmelidir.

---

# 12. Video Generation Input

İlk MVP'de minimum input:

### Required

**Topic**

Örneğin:

> Why you should stop taking meeting notes manually.

**Template**

```text
Story
List
POV
Problem/Solution
```

### Optional

**Target duration**

Default:

**18 seconds**

Allowed:

**15–25 seconds**

---

# 13. Script Generation

LLM aşağıdaki context'i alacaktır:

```text
Persona
+
Topic
+
Template
+
Target duration
```

ve TikTok-native script oluşturacaktır.

Script:

* ilk 1–2 saniyede hook içermeli,
* conversational olmalı,
* gereksiz intro içermemeli,
* hedef süreye uygun kelime sayısında olmalı,
* persona'nın tone'una uymalı,
* fake personal experience yaratmamalıdır.

Örneğin:

```text
Most people still take meeting notes like it's 2015.

You listen, type, miss something, then spend another
20 minutes cleaning everything up.

Your phone can already do this for you.

Record it. Transcribe it. Summarize it.

Done.
```

---

# 14. Voice Generation

Voice provider:

**ElevenLabs**

Her persona bir `voice_id` ile ilişkilendirilecektir.

Workflow:

```text
Script
 ↓
ElevenLabs
 ↓
voice.mp3
 ↓
alignment/timestamps
 ↓
actual duration
```

Önemli requirement:

> Video timing, tahmini script süresine değil gerçek ElevenLabs audio duration'ına göre oluşturulmalıdır.

Örneğin target duration 18 saniye olmasına rağmen voice 20.3 saniye ise scene planning 20.3 saniyeye göre ayarlanmalıdır.

Belirlenen maksimum süre aşılırsa script otomatik kısaltılıp voice yeniden oluşturulabilir.

---

# 15. Caption System

Voice-over'dan caption üretilecektir.

Caption voice ile synchronized olmalıdır.

Tercihen ElevenLabs alignment/timestamp datası kullanılacaktır.

Caption özellikleri:

* 2–5 kelimelik chunks
* high readability
* TikTok-safe positioning
* current word/phrase emphasis
* simple animation
* maximum two lines

Örnek:

```text
Most people

still take

MEETING NOTES

like it's 2015.
```

Caption style configuration olarak tutulmalıdır.

---

# 16. Video JSON

LLM'in nihai structured output'u `Video JSON` olacaktır.

Örnek:

```json
{
  "version": "1.0",
  "persona": "young_professional",
  "template": "story_v1",
  "topic": "Stop taking meeting notes manually",

  "voiceover": {
    "text": "Most people still take meeting notes...",
    "audio": "voice_239.mp3",
    "duration": 18.7
  },

  "scenes": [
    {
      "start": 0,
      "end": 2.4,
      "asset_id": "asset_042",
      "asset_start": 1.2,
      "text": "Stop taking\nmeeting notes."
    },
    {
      "start": 2.4,
      "end": 6.3,
      "asset_id": "asset_014",
      "asset_start": 2.1,
      "text": null
    },
    {
      "start": 6.3,
      "end": 10.8,
      "asset_id": "asset_081",
      "asset_start": 0.8,
      "text": "Listen → Type → Fix"
    },
    {
      "start": 10.8,
      "end": 14.5,
      "asset_id": "asset_023",
      "asset_start": 1.4,
      "text": null
    },
    {
      "start": 14.5,
      "end": 18.7,
      "asset_id": "asset_067",
      "asset_start": 0.5,
      "text": "Record. Transcribe. Done."
    }
  ],

  "caption_style": "dynamic_center",
  "music": "background_01"
}
```

Video JSON schema validate edilmeden renderer'a gönderilmemelidir.

---

# 17. Scene Planning

Scene değişimleri sabit 5 saniyelik bloklara göre yapılmamalıdır.

Scene boundary'leri:

* sentence changes
* semantic changes
* visual concepts
* hook/payoff structure

üzerinden belirlenmelidir.

Genel hedef:

**1.5–4 saniye / shot**

Ancak template ihtiyacına göre değişebilir.

---

# 18. Rendering Engine

MVP rendering engine:

**FFmpeg**

Output specification:

```text
Resolution: 1080 × 1920
Aspect ratio: 9:16
Format: MP4
Codec: H.264
Audio: AAC
FPS: 30
```

Renderer aşağıdaki işlemleri desteklemelidir:

* asset trimming
* concatenation
* crop
* scale
* text overlays
* subtitles
* voice-over
* background music
* basic zoom
* audio normalization
* audio ducking

---

# 19. Visual Variation

Videoların otomatik edit edilmiş görünümünü azaltmak için renderer minimum variation uygulamalıdır.

Desteklenecek özellikler:

### Random usable start

8 saniyelik asset'in her zaman ilk saniyesi kullanılmamalıdır.

### Subtle zoom

Örneğin:

```text
100% → 104%
```

### Dynamic crop

4K kaynaklardan farklı crop kullanılabilir.

### Variable shot duration

Shot süreleri sürekli aynı olmamalıdır.

### Limited transitions

MVP'de ağırlıklı olarak hard cut kullanılmalıdır.

Gereksiz transition kullanılmamalıdır.

---

# 20. Background Music

MVP'de küçük bir royalty-safe background music library bulunacaktır.

Örneğin:

```text
music/
    energetic_01.mp3
    chill_01.mp3
    productivity_01.mp3
```

Music voice-over'ın altında tutulacaktır.

Default volume:

yaklaşık **-20 dB** relative background level.

Voice her zaman dominant olmalıdır.

---

# 21. User Interface

MVP web UI minimum tutulacaktır.

## Generate Screen

```text
TikTok Content Factory

PERSONA
Young Professional

TEMPLATE
[ Story ▼ ]

TOPIC
┌───────────────────────────────┐
│ Stop taking meeting notes    │
└───────────────────────────────┘

DURATION
[ 18 sec ]

        GENERATE VIDEO
```

---

# 22. Generation States

UI aşağıdaki durumları göstermelidir:

```text
Generating script...
        ↓
Generating voice...
        ↓
Planning scenes...
        ↓
Selecting B-roll...
        ↓
Generating captions...
        ↓
Rendering video...
        ↓
Ready
```

Generation background job olarak çalışabilmelidir.

---

# 23. Result Screen

Generation tamamlandığında:

```text
VIDEO PREVIEW

▶ 00:18

Template
Story

Assets
5 clips

Voice
Young Professional

Script
────────────────
Most people still...
────────────────

[CHANGE ASSETS]

[REGENERATE SCRIPT]

[RENDER AGAIN]

[APPROVE]
```

---

# 24. Regeneration Controls

Bu MVP'nin önemli requirement'larından biridir.

Kullanıcı tüm generation pipeline'ını yeniden çalıştırmak zorunda kalmamalıdır.

### Regenerate Script

Yeni:

* hook
* script
* voice
* scene plan

oluşturur.

### Change Assets

Script ve voice aynı kalır.

Sadece B-roll yeniden seçilir ve render yapılır.

### Render Again

Aynı content ile visual variation oluşturur.

Örneğin farklı:

* crop
* asset start point
* shot sequence

kullanabilir.

### Approve

Video `approved` olarak işaretlenir.

---

# 25. Data Model

Minimum entities:

```text
Persona
Asset
Template
VideoProject
VideoScene
VoiceGeneration
Render
```

### VideoProject

Örneğin:

```text
id
persona_id
template_id
topic
script
target_duration
actual_duration
status
created_at
approved_at
```

### VideoScene

```text
id
video_project_id
asset_id
start_time
end_time
asset_start_time
overlay_text
order
```

---

# 26. Recommended Technical Stack

### Backend

**Python + FastAPI**

### Database

**PostgreSQL**

### Video processing

**FFmpeg**

### AI

LLM abstraction layer.

İlk provider OpenAI veya Claude olabilir; business logic doğrudan provider'a bağımlı olmamalıdır.

### Voice

**Elevenlabs

## 27. Recommended Technical Stack

### Backend

**Python + FastAPI**

Responsibilities:

* project creation
* persona loading
* template loading
* LLM orchestration
* asset selection
* ElevenLabs integration
* render job management
* FFmpeg execution
* project state management

### Database

**PostgreSQL**

MVP'de aşağıdaki veriler tutulacaktır:

* assets
* asset metadata
* templates
* persona
* generated projects
* scene plans
* generation history
* asset usage history
* render outputs

### Video Processing

**FFmpeg**

FFmpeg aşağıdakilerden sorumludur:

* trim
* crop
* resize
* concatenate
* zoom
* text rendering
* subtitles
* voice-over mixing
* music mixing
* final encoding

### LLM

Provider abstraction kullanılacaktır.

Başlangıçta:

**OpenAI veya Claude**

kullanılabilir.

Business logic doğrudan tek provider'a bağlı olmamalıdır.

Örneğin:

```python
generate_script()
generate_scene_plan()
select_assets()
```

gibi internal interfaces bulunmalıdır.

### Voice

**ElevenLabs**

MVP'de:

* tek voice
* tek persona
* English US

kullanılacaktır.

Mümkünse timestamp/alignment destekleyen endpoint kullanılmalıdır.

### Storage

MVP için:

```text
Local filesystem
```

yeterlidir.

Örneğin:

```text
/storage
    /assets
    /music
    /voice
    /renders
    /projects
```

İleride:

```text
Cloudflare R2 / S3
```

kullanılabilir.

### Frontend

**Next.js**

Ancak ilk teknik milestone için frontend zorunlu değildir.

Önce CLI/API ile video generation engine doğrulanmalıdır.

---

# 28. Recommended Project Structure

```text
tiktok-content-factory/

backend/

    app/

        api/

        assets/
            importer.py
            selector.py
            metadata.py

        personas/
            loader.py

        templates/
            loader.py

        content/
            script_generator.py
            scene_planner.py

        voice/
            elevenlabs.py
            alignment.py

        captions/
            generator.py

        renderer/
            ffmpeg.py
            filters.py
            audio.py
            subtitles.py

        projects/
            service.py

        models/

        schemas/

        config/

frontend/

storage/

    assets/

    music/

    voices/

    renders/

    temp/

configs/

    personas/
        young_professional.json

    templates/
        story_v1.json
        list_v1.json
        pov_v1.json
        problem_solution_v1.json
```

Config-driven architecture zorunludur.

Yeni persona veya template eklemek için core renderer'ın değiştirilmesi gerekmemelidir.

---

# 29. Generation Pipeline

Tam generation pipeline:

```text
CREATE PROJECT
      ↓
Load Persona
      ↓
Load Template
      ↓
Generate Script
      ↓
Generate ElevenLabs Voice
      ↓
Get Real Voice Duration
      ↓
Generate Voice Alignment
      ↓
Divide Script Into Semantic Segments
      ↓
Scene Planning
      ↓
Asset Candidate Search
      ↓
Asset Selection
      ↓
Create Video JSON
      ↓
Validate JSON
      ↓
Generate Captions
      ↓
FFmpeg Render
      ↓
Quality Validation
      ↓
Preview
```

Bu pipeline mümkün olduğunca modüler olmalıdır.

Örneğin asset değiştirmek için:

```text
script generation
voice generation
```

tekrar çalıştırılmamalıdır.

---

# 30. Important Pipeline Rule

Generation order özellikle şu şekilde olmalıdır:

```text
Script
 ↓
Voice
 ↓
Actual Voice Duration
 ↓
Scene Planning
 ↓
Assets
 ↓
Render
```

Şu şekilde olmamalıdır:

```text
Script
 ↓
18 second scene plan
 ↓
Voice = 21.7 seconds
```

Voice gerçek video timeline'ının master clock'u olacaktır.

---

# 31. Asset Selection Flow

Her scene için LLM'e bütün asset library gönderilmemelidir.

Önce backend basit filtering yapmalıdır.

Örneğin scene:

```text
"People waste time manually writing meeting notes."
```

Backend candidate oluşturur:

```text
typing
writing
notebook
desk
laptop
working
```

Bu tag'lere uygun 10–20 asset bulunur.

Sonra LLM bu candidate set içerisinden seçim yapar.

```text
Scene
 ↓
Tag extraction
 ↓
DB filtering
 ↓
15 candidate assets
 ↓
LLM ranking
 ↓
Selected asset
```

Bu mimari ileride asset library büyüdüğünde sistemi daha ölçeklenebilir yapacaktır.

---

# 32. Asset Reuse Prevention

Aynı görüntünün sürekli tekrarlanmasını azaltmak için:

```text
usage_count
last_used_at
last_used_project_id
```

tutulmalıdır.

Selection score:

```text
final_score =
    relevance_score
    × quality_score
    × freshness_score
```

Örneğin:

```text
Never used       = 1.00

7+ days ago       = 0.90

3–7 days          = 0.70

1–3 days          = 0.45

Used today        = 0.20
```

Bu değerler daha sonra değiştirilebilir.

---

# 33. Asset Start Point Selection

Bir source clip:

```text
8 seconds
```

olabilir.

Scene:

```text
2.4 seconds
```

gerektiriyorsa aynı clip sürekli:

```text
0:00 → 0:02.4
```

kullanılmamalıdır.

Sistem:

```text
usable_start
usable_end
```

içinden random veya quality-aware segment seçmelidir.

Örneğin:

```text
Source:
1.0 → 7.5 usable

Required:
2.5 sec

Possible:
1.2 → 3.7
2.9 → 5.4
4.5 → 7.0
```

Bu asset reuse hissini ciddi şekilde azaltacaktır.

---

# 34. Scene Rendering Rules

Default:

```text
Scene duration:
1.5–4 sec
```

İstisna:

* product demo
* important payoff
* text-heavy section

daha uzun olabilir.

Bir video mümkünse:

```text
4–8 scenes
```

içermelidir.

18 saniyelik normal video için ideal:

```text
5–6 B-roll clips
```

---

# 35. Text Layers

İki farklı text sistemi olacaktır.

## Captions

Voice'un söylediği kelimeler.

Sürekli bulunabilir.

## Creative Overlay

LLM tarafından scene için özel oluşturulan büyük text.

Örneğin:

```text
STOP DOING THIS
```

veya:

```text
30 MINUTES → 10 SECONDS
```

Creative overlay her scene'de kullanılmamalıdır.

MVP hedefi:

**Video başına 1–3 creative overlay.**

---

# 36. Safe Zones

TikTok UI nedeniyle text:

* en alta,
* en sağ kenara,
* aşırı yukarıya

yerleştirilmemelidir.

Renderer ortak bir TikTok safe-area kullanmalıdır.

Örneğin:

```text
Top reserved:
~10%

Bottom reserved:
~18%

Right reserved:
~12%
```

Caption ve headline'lar safe area içerisinde kalmalıdır.

---

# 37. Caption Styles

MVP'de tek güçlü caption style yeterlidir.

### dynamic_center

Characteristics:

* white/bold text
* high contrast
* maximum 4–5 words
* 1–2 lines
* current phrase emphasis
* center/lower-center positioning

Animation:

```text
FAST FADE / POP
```

Abartılı word-by-word animation zorunlu değildir.

---

# 38. Voice Configuration

Persona config:

```json
{
  "provider": "elevenlabs",
  "voice_id": "VOICE_ID",
  "speed": 1.05,
  "stability": 0.55,
  "similarity_boost": 0.75
}
```

Gerçek değerler test sonrası değiştirilebilir.

Ama bütün videolarda aynı creator karakterinin korunması için aynı voice profile kullanılmalıdır.

---

# 39. Script Duration Handling

Script generation sırasında LLM'e yaklaşık hedef kelime sayısı verilebilir.

Örneğin:

```text
15 sec → ~35–45 words
20 sec → ~45–60 words
25 sec → ~60–70 words
```

Ancak final karar ElevenLabs audio duration'ına göre verilmelidir.

Eğer:

```text
target max = 20 sec

actual voice = 24.6 sec
```

ise sistem otomatik:

```text
shorten_script()
```

çalıştırabilir.

Maximum:

**2 automatic rewrite attempts.**

Sonrasında hata kullanıcıya gösterilebilir.

---

# 40. Background Music Selection

Music MVP'de AI tarafından sofistike seçilmek zorunda değildir.

Template veya persona üzerinden default music category seçilebilir.

Örneğin:

```text
Story → productivity_soft

List → upbeat

POV → minimal

Problem/Solution → upbeat
```

Music library başlangıçta 5–10 track olabilir.

---

# 41. Rendering Quality Checks

Render bittikten sonra otomatik kontroller yapılmalıdır.

Minimum:

```text
file exists
duration > 10 sec
duration < 30 sec
resolution = 1080 × 1920
audio stream exists
video stream exists
FPS valid
file size > minimum threshold
```

Başarısız render kullanıcıya `READY` olarak gösterilmemelidir.

---

# 42. Manual Review

MVP'de final karar insandadır.

User:

```text
Generate
 ↓
Watch
 ↓
Approve / Modify
```

TikTok'a otomatik paylaşım yoktur.

Bu önemli çünkü sistemin ilk aşamasında amaç **video üretim kalitesini öğrenmek**, distribution otomasyonu değildir.

---

# 43. Project Statuses

```text
DRAFT
GENERATING_SCRIPT
GENERATING_VOICE
PLANNING
SELECTING_ASSETS
RENDERING
READY
APPROVED
FAILED
```

Frontend generation progress göstermek için bunları kullanabilir.

---

# 44. Failure Handling

Her stage bağımsız retry edilebilir olmalıdır.

Örneğin ElevenLabs başarısız oldu:

```text
Script tekrar generate edilmez.
```

Sadece:

```text
Voice generation
```

retry edilir.

FFmpeg başarısız oldu:

```text
LLM
ElevenLabs
Asset selection
```

tekrar çağrılmaz.

Sadece render tekrar denenir.

Bu hem maliyet hem debugging açısından önemlidir.

---

# 45. Regeneration Architecture

Project'in her generation artifact'i saklanmalıdır.

Örneğin:

```text
Project 001

script_v1
voice_v1
plan_v1
render_v1

asset_swap

plan_v2
render_v2
```

Böylece kullanıcı:

**Change Assets**

dediğinde önceki script ve voice korunabilir.

---

# 46. MVP CLI

Frontend'den önce aşağıdaki gibi bir command çalışmalıdır:

```bash
python generate.py \
  --template story_v1 \
  --topic "Stop taking meeting notes manually"
```

Output:

```text
Creating project...
Script generated.
Voice generated: 18.4 sec
5 scenes generated.
Assets selected.
Rendering...

✓ output/project_001/final.mp4
```

Bu çalışmadan frontend geliştirmeye başlanmamalıdır.

---

# 47. Minimum API

Frontend geldiğinde aşağıdaki minimum API yeterlidir.

```text
POST /projects
GET  /projects/:id

POST /projects/:id/generate

POST /projects/:id/regenerate-script

POST /projects/:id/change-assets

POST /projects/:id/render

POST /projects/:id/approve

GET /assets

POST /assets/import

GET /templates
```

---

# 48. Asset Management Screen

MVP UI'nın ikinci ekranı Asset Library olabilir.

```text
ASSET LIBRARY

[ + IMPORT ]

---------------------------------

▶ typing_01

Action:
typing

Location:
office

Shot:
close

Tags:
desk, work, laptop

Quality:
★★★★★

Approved:
✓
```

User metadata'yı değiştirebilmelidir.

---

# 49. Manual Asset Override

Result screen'de scene'ler görülebilmelidir.

```text
SCENE 1
0:00–0:02.3

[preview]

asset_043

[CHANGE]
```

`CHANGE` seçildiğinde sistem uygun alternatif B-roll'ları gösterebilir.

```text
Suggested assets:

asset_023
asset_071
asset_112
```

Kullanıcı birini seçip yeniden render edebilir.

Bu özellik MVP için değerlidir çünkü yanlış B-roll seçimi tüm videoyu çöpe atmamalıdır.

---

# 50. MVP Success Metrics

İlk aşamada TikTok performance metrikleri ürünün ana başarı kriteri değildir.

Önce generation system'i ölçmeliyiz.

### Primary

**Publishable Rate**

Kaç generated video minimum değişiklikle yayınlanabilecek durumda?

MVP hedef:

```text
≥ 70%
```

### Generation Success Rate

Technical olarak tamamlanan generation:

```text
≥ 95%
```

### Asset Selection Acceptance

AI'ın ilk seçtiği B-roll'ların kullanıcı tarafından değiştirilmeden kabul edilme oranı:

Başlangıç hedef:

```text
≥ 70%
```

### Script Acceptance

İlk script'in kabul oranı:

```text
≥ 75%
```

### Manual Work

Her generated video için kullanıcı müdahalesi:

Hedef:

```text
< 2 minutes
```

Posting bu süreye dahil değildir.

---

# 51. MVP Validation Test

İlk gerçek test:

**30 video üretmek.**

Tek persona.

Distribution:

```text
Story                10
List                  7
POV                   6
Problem/Solution      7

TOTAL                30
```

Bu 30 video gerçek TikTok hesabında kullanılmalıdır.

Her video için kaydedilecek internal değerlendirme:

```text
Script:
1–5

B-roll:
1–5

Voice:
1–5

Captions:
1–5

Edit:
1–5

Would post:
Yes / No

Manual changes:
count
```

---

# 52. MVP Acceptance Criteria

MVP tamamlanmış sayılması için:

* [ ] En az 100 B-roll asset import edilebiliyor.
* [ ] Asset metadata saklanabiliyor.
* [ ] Tek persona config üzerinden çalışıyor.
* [ ] 4 template kullanılabiliyor.
* [ ] Topic girilerek script üretilebiliyor.
* [ ] ElevenLabs voice oluşturulabiliyor.
* [ ] Gerçek voice duration alınabiliyor.
* [ ] Script semantic scene'lere bölünebiliyor.
* [ ] Her scene için B-roll otomatik seçiliyor.
* [ ] Aynı asset'in sürekli seçilmesi önleniyor.
* [ ] Video JSON oluşturuluyor.
* [ ] Video JSON schema validation yapılıyor.
* [ ] Dynamic captions oluşturuluyor.
* [ ] Creative text overlay destekleniyor.
* [ ] Background music ekleniyor.
* [ ] Voice/music mixing yapılıyor.
* [ ] FFmpeg ile 1080×1920 MP4 oluşturuluyor.
* [ ] Kullanıcı preview izleyebiliyor.
* [ ] Script regenerate edilebiliyor.
* [ ] B-roll değiştirilebiliyor.
* [ ] Aynı projeden yeniden render alınabiliyor.
* [ ] Video approve edilebiliyor.
* [ ] 30-video validation batch'i tamamlanabiliyor.

---

# 53. Development Milestones

## Milestone 1 — Asset Engine

Deliverable:

```text
B-roll folder
↓
import
↓
metadata
↓
database
↓
search/select
```

Bu milestone sonunda:

> “typing + desk + close”

gibi query ile uygun asset bulunabilmelidir.

---

## Milestone 2 — Content Engine

Deliverable:

```text
Topic
+
Persona
+
Template

↓

Script
+
structured scene intent
```

Henüz video üretmek gerekmez.

---

## Milestone 3 — Voice Engine

Deliverable:

```text
Script
↓
ElevenLabs
↓
MP3
+
alignment
+
duration
```

---

## Milestone 4 — Video Planning Engine

Deliverable:

```text
Voice
+
Script
+
Assets
+
Template

↓

Video JSON
```

Örneğin terminalde tam scene plan görülebilmelidir.

---

## Milestone 5 — Renderer

Deliverable:

```text
Video JSON
↓
FFmpeg
↓
1080×1920 MP4
```

Bu milestone projenin **asıl MVP breakthrough noktasıdır.**

---

## Milestone 6 — Controls

Eklenir:

```text
Change Asset
Regenerate Script
Render Again
Approve
```

---

## Milestone 7 — Minimal Web UI

Backend doğrulandıktan sonra:

```text
Generate
Preview
Modify
Approve
```

interface'i geliştirilir.

---

# 54. MVP Development Order

Önerilen kesin sıra:

```text
1. Asset folder
2. Metadata schema
3. Asset importer
4. Persona config
5. Template configs
6. Script generation
7. ElevenLabs
8. Audio alignment
9. Scene planner
10. Asset selector
11. Video JSON schema
12. FFmpeg renderer
13. Captions
14. Music
15. Regeneration
16. Web UI
17. 30-video test
```

UI'ı önce geliştirmemek özellikle önemlidir.

Önce:

```text
Topic → MP4
```

pipeline'ı terminalden kusursuz çalışmalıdır.

---

# 55. First Working Prototype

İlk çalışan prototype sadece şunu yapmalıdır:

Input:

```text
Topic:
3 productivity habits that waste your time

Template:
list_v1
```

System:

```text
✓ Persona loaded

✓ Script generated

✓ ElevenLabs voice
18.9 sec

✓ 5 scenes

✓ B-roll
asset_014
asset_062
asset_031
asset_088
asset_043

✓ Captions

✓ Render
```

Output:

```text
/output/001/final.mp4
```

Video:

```text
1080 × 1920
18.9 sec
30 FPS
H.264
AAC
```

Bunu elde ettiğimiz anda MVP'nin core hypothesis'i teknik olarak kanıtlanmış olur.

---

# 56. Post-MVP Roadmap

MVP başarılı olursa sırayla:

### V1.1 — Automatic Ideas

Topic'i kullanıcı vermek zorunda kalmaz.

```text
Persona
↓
AI
↓
20 topics
```

### V1.2 — Multiple Personas

```text
Young Professional
Founder
Productivity
AI Tools
...
```

Her persona:

* voice
* content rules
* captions
* visual preferences

taşıyabilir.

### V1.3 — Asset Embeddings

Asset library büyüdüğünde semantic vector search.

### V1.4 — Product Library

Business Card AI, Stampify, PDFero vb. için structured product context + screen recording assets.

### V1.5 — Content Calendar

```text
7 days
×
2 videos
```

otomatik batch generation.

### V1.6 — Performance Feedback

TikTok sonuçları:

```text
views
watch time
completion
shares
saves
profile visits
```

Video metadata ile ilişkilendirilir.

### V1.7 — Learning Engine

Sistem:

```text
Persona
×
Hook
×
Topic
×
Template
×
Duration
```

kombinasyonlarının performansını öğrenir.

### V1.8 — Multi-Account Factory

Son aşamada:

```text
10 personas
×
2 videos/day
=
20 videos/day
```

hedeflenen creator network sistemine geçilir.

---

# 57. Final MVP Definition

Bu ürünün ilk versiyonu şu cümleyle tanımlanmalıdır:

> **“Give it a topic and a template; get a TikTok-ready video made from my own B-roll, AI voice and dynamic text.”**

MVP bunun dışına çıkmamalıdır.

İlk versiyonda **trend sistemi, posting, analytics, 10 hesap, otomatik content calendar veya karmaşık AI video üretimi eklemek hata olur.**

Core loop:

```text
TOPIC
  ↓
TEMPLATE
  ↓
PERSONA
  ↓
SCRIPT
  ↓
ELEVENLABS
  ↓
SCENE PLAN
  ↓
MY B-ROLL
  ↓
TEXT + CAPTIONS
  ↓
FFMPEG
  ↓
TIKTOK-READY VIDEO
```

Bu loop kaliteli çalıştığında geri kalan sistem bunun üzerine katman olarak eklenebilir.


