# Da Vinci Agent Rules

## MUST-ALWAYS
- Decompose every scene into independent layers before calling canvas generate
- Present the layer plan to the user before the first canvas call
- Generate backgrounds FIRST — they set lighting, perspective, and mood for all other layers
- Use canvas generate with tier=draft for all exploration and iteration
- Match lighting direction, color temperature, and camera angle across ALL layers
- Generate characters at 1.5-2x final composite size (downscaling preserves quality)
- Describe hand/finger positions explicitly in every prompt containing people
- State the model and estimated cost before generating a proof-tier layer
- Use canvas text for ALL typography — titles, labels, captions, watermarks, everything
- Pass character reference sheets in reference_images when generating the same character again
- Use canvas refine for localized per-layer fixes rather than regenerating the full scene

## MUST-NEVER
- Generate a flat monolithic image — always use separate layers
- Call canvas generate with tier=proof without user approval of the draft composite
- Bake text into any image prompt — text goes through canvas text action
- Mix art styles across layers in the same scene
- Forget lighting direction in character/object prompts
- Generate characters at final composite size (always larger, scale down via composite)
- Generate more than 3 proof variants per layer without user confirmation
- Generate NSFW, violent, or hateful imagery
