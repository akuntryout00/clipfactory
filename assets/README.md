# B-roll library

Your own clips, never committed. Layout:

```
assets/<persona_id>/<category>/<clip>.mp4     e.g. assets/indie_maker/desk/typing_01.mp4
assets/<persona_id>/_originals/               untrimmed sources (ignored by the importer)
assets/<persona_id>/_rejected/                takes you dropped (ignored by the importer)
assets/broll_database.json                    optional seed: [{"id","file","description","tags","shot",...}] read by `make import`
```

Use the web UI (B-roll → Add video) or drop files here and run `make import`. The B-roll page's **shot list** tells you what to film for each persona and how much of it is covered.
