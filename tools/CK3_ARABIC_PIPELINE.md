# CK3 Arabic pipeline

This tool works with any CK3 mod root or `localization/english` folder.

## One-time setup

Put Gemini API keys, one per line, in `tools/gemini_keys.txt`. Do not commit that file.

Install the shaping libraries:

```powershell
python -m pip install arabic-reshaper python-bidi
```

## Translate and shape a new mod

From the `tools` folder, run:

```powershell
python ck3_arabic_pipeline.py "C:\Path\To\SomeMod"
```

The pipeline finds `localization/english`, creates a timestamped ZIP backup in
`tools/backups`, translates values with Gemini, shapes Arabic with
`arabic-reshaper` and reorders it with `python-bidi`.

Use this when Arabic translation already exists and only shaping is needed:

```powershell
python ck3_arabic_pipeline.py "C:\Path\To\SomeMod\localization\english" --shape-only
```

Preview whether unshaped Arabic remains without writing files:

```powershell
python ck3_arabic_pipeline.py "C:\Path\To\SomeMod" --dry-run
```

Never manually run the old character-map script. The library-based shaper skips
already-shaped values, so it is safe to use when adding new raw Arabic values.
