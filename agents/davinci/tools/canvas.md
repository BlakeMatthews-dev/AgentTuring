---
name: canvas
description: Layer-based image compositing engine. Generates, refines, and assembles image layers.
groups: [image, creative]
parameters:
  type: object
  properties:
    action:
      type: string
      enum: [generate, refine, reference, composite, text]
      description: |
        generate  — Create a single image layer (background, character, or object)
        refine    — Fix artifacts on a layer via img2img editing
        reference — Generate a multi-view character reference sheet
        composite — Assemble layers into a final image
        text      — Render typography on the canvas
    layer_type:
      type: string
      enum: [background, character, object]
      description: "Type of layer to generate. Required for 'generate' action."
    tier:
      type: string
      enum: [draft, proof]
      default: draft
      description: "draft = cheap/fast models for iteration, proof = premium for final output."
    prompt:
      type: string
      description: "Text prompt describing what to generate or refine."
    source_image:
      type: string
      description: "Path/URL to source image. Required for 'refine' action."
    reference_images:
      type: array
      items:
        type: string
      maxItems: 4
      description: "Reference images for style/character consistency."
    region:
      type: string
      description: "Region to refine: 'hands', 'face', 'background', 'full', or crop box 'x1,y1,x2,y2'."
      default: full
    strength:
      type: number
      minimum: 0.1
      maximum: 1.0
      default: 0.6
      description: "Img2img strength: 0.1=subtle, 0.6=moderate, 1.0=full regeneration."
    aspect_ratio:
      type: string
      enum: ["1:1", "16:9", "9:16", "3:2", "2:3", "4:3", "3:4"]
      default: "1:1"
    negative_prompt:
      type: string
      default: "no text, no watermark, no signature"
    count:
      type: integer
      minimum: 1
      maximum: 4
      default: 2
      description: "Number of variants to generate."
    layers:
      type: array
      description: "Layer definitions for 'composite' action. Each layer has: image, x, y, scale, rotation, z_index."
      items:
        type: object
        properties:
          image:
            type: string
          x:
            type: integer
          y:
            type: integer
          scale:
            type: number
            default: 1.0
          rotation:
            type: number
            default: 0
          z_index:
            type: integer
            default: 0
    text_content:
      type: string
      description: "Text to render for 'text' action."
    text_style:
      type: object
      description: "Font style for 'text' action: font, size, color, weight, alignment, shadow."
      properties:
        font:
          type: string
          default: "sans-serif"
        size:
          type: integer
          default: 48
        color:
          type: string
          default: "#FFFFFF"
        weight:
          type: string
          enum: [normal, bold]
          default: normal
        alignment:
          type: string
          enum: [left, center, right]
          default: center
    lighting:
      type: string
      description: "Light source description for cross-layer consistency."
    perspective:
      type: string
      description: "Camera angle/lens for cross-layer consistency."
  required: [action]
endpoint: ""
auth_key_env: ""
trust_tier: t1
---

## Canvas Tool — Layer-Based Image Compositing

The canvas tool is Da Vinci's primary instrument. It handles all image generation,
refinement, and compositing operations. Da Vinci calls it multiple times per scene.

### Actions

**generate** — Create a single image layer
- Requires: `action`, `prompt`, `layer_type`, `tier`
- Background layers: generates full environment (no characters/objects)
- Character/object layers: generates on isolated white/transparent background
- Prompt is augmented based on layer_type (isolation, negative prompts)

**refine** — Fix artifacts on an existing layer
- Requires: `action`, `source_image`, `prompt`
- Optional: `region` (crop to hands/face/etc), `strength`, `reference_images`
- Uses Kontext Pro for targeted editing

**reference** — Generate a character reference sheet
- Requires: `action`, `prompt` (character description)
- Generates hero image → turnaround views via img2img
- Returns a composite sheet for use as reference_images in future calls

**composite** — Assemble layers into final image
- Requires: `action`, `layers` (array of layer definitions with position/scale/rotation)
- Each layer has x, y, scale, rotation, z_index
- Layers are composited back-to-front by z_index

**text** — Render typography
- Requires: `action`, `text_content`, `text_style`
- Rendered by canvas text engine, NOT by AI models
- Always pixel-perfect — no garbled AI text

### Model Selection

The tool selects models based on the `tier` parameter:

**Draft tier** (fast, free or near-free):
1. google-gemini-2.5-flash-image (FREE, 500/day)
2. together-black-forest-labs/flux.1-schnell (FREE promo)
3. together-rundiffusion/juggernaut-lightning-flux ($0.002)
4. together-stabilityai/stable-diffusion-xl ($0.002)
5. imagen-4-fast (FREE, rate-limited)

**Proof tier** (premium quality):
1. google-gemini-3-pro-image (FREE, rate-limited)
2. imagen-4-ultra (FREE, rate-limited)
3. together-black-forest-labs/flux.2-pro ($0.03)
4. together-black-forest-labs/flux.1.1-pro ($0.04)
5. together-ideogram-ai/ideogram-3.0 ($0.06)

**Refine**: together-black-forest-labs/flux.1-kontext-pro ($0.04)
