# Caption fonts

Fonts in this folder are offered in the UI (System → Captions, and per project) and passed to libass as `fontsdir`
when rendering. Drop any `.ttf` / `.otf` here (or upload from the System page) and it appears in the font list —
the family name is read from the file.

Bundled (all SIL Open Font License 1.1, see OFL.txt):

| File | Family | Source |
|---|---|---|
| Anton-Regular.ttf | Anton | Vernon Adams (google/fonts) |
| BebasNeue-Regular.ttf | Bebas Neue | Dharma Type (google/fonts) |
| Poppins-Bold.ttf | Poppins | Indian Type Foundry (google/fonts) |
| Montserrat-ExtraBold.ttf | Montserrat | Julieta Ulanovsky et al. |
| Oswald-Bold.ttf | Oswald | Vernon Adams et al. |

DejaVu Sans (the default) comes from the Docker image (`fonts-dejavu-core`).
