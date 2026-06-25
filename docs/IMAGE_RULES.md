# Image Rules

Korea Easy Guide uses AI-generated raster images for polished public posts. Local SVG assets are zero-cost fallback assets for unattended CI/production automation when Codex image generation is not available inside the Python pipeline.

## Default Post Image Structure

Each published post should include:

1. Hero image near the top of the article.
2. One inline image before the Step-by-Step Guide section.
3. Optional second inline image for long posts, placed before Useful Tips or FAQ.

## Preferred Style

- Realistic editorial travel photography.
- Bright natural daylight.
- Clean Korea travel context: airport, station, taxi pickup, street navigation, cafe, store, hotel, or transit area.
- Practical and trustworthy, not dramatic or cinematic.
- Horizontal 16:9 composition.
- Save polished Codex images as compressed JPG around 1200x675 before embedding in Blogger. Automated CI fallback assets may use SVG with the same logical filenames.

## Prompt Requirements

Every image prompt should specify:

- Use case: `photorealistic-natural`
- Asset type: hero or inline image, and the exact blog post topic.
- Primary request: what the image should help explain.
- Scene/backdrop: the Korea travel or daily-life location.
- Subject: foreign visitor or traveler action.
- Style/medium: realistic editorial photography.
- Composition/framing: horizontal 16:9, clean blog layout.
- Lighting/mood: bright, calm, helpful, trustworthy.
- Color palette: restrained travel-guide tones.
- Constraints: no readable text, logos, brand marks, watermark, distorted hands, or extra fingers.
- Avoid: fake official UI, readable app screens, QR codes, barcodes, clutter, cartoon/vector style.

## Brand and Accuracy Rules

- Do not show real app logos such as Kakao, Naver, Google, Apple, Android, telecom carriers, airlines, or rail operators.
- Do not show readable Korean or English signage as the main subject.
- Do not show scannable QR codes or barcodes.
- Smartphone screens must use generic maps, generic route lines, simple icons, or blurred interfaces.
- Images should support the article, not pretend to be official documentation.

## Easy PC Fix Guide Image Rules

Windows help images must be safe explanatory visuals, not fake documentation.

- Do not generate fake Windows UI, fake Microsoft support screens, fake error dialogs, or readable error-code screens.
- Do not show command prompts, PowerShell windows, Registry Editor, BIOS/UEFI screens, partition tools, reset screens, or scary warning overlays.
- Use abstract repair symbols, checklists, shields, restart arrows, clocks, blank cards, and generic laptop/desk scenes.
- Prompts must explicitly say to avoid fake Windows UI, readable UI/error text, command prompts, and registry editors.
- Alt text and captions must describe the image as an abstract help visual or checklist, not as a screenshot or exact UI screen.
- Hades blocks Windows posts when `image_plan.json` lacks those safety guards.

## Prompt Template

```text
Use case: photorealistic-natural
Asset type: <hero|inline> image for an English Korea travel guide blog post about <topic>
Primary request: Create a premium realistic editorial travel photo that helps explain <specific reader problem>.
Scene/backdrop: <Korea-specific setting>, clean and practical, no dominant readable signage.
Subject: <foreign traveler action>, with <relevant object/app/transport> shown generically.
Style/medium: realistic editorial photography, premium practical travel guide image.
Composition/framing: horizontal 16:9, <foreground subject>, <midground context>, uncluttered.
Lighting/mood: bright natural daylight, calm, helpful, trustworthy.
Color palette: <topic-appropriate restrained colors>.
Constraints: no readable text, no logos, no brand marks, no watermark, no distorted hands, no extra fingers.
Avoid: fake official UI, QR codes, barcodes, clutter, cartoon/vector art, dark cinematic lighting.
```

## Workflow

1. Generate with Codex image generation, not the OpenAI Images API pipeline.
2. Copy the selected image into the article `assets/` directory.
3. Keep the original generated image in the Codex generated images folder.
4. Convert polished generated images to JPG:

```bash
sips -s format jpeg -s formatOptions 78 -z 675 1200 source.png --out ai-hero.jpg
```

5. Reference it in article HTML as `assets/ai-hero.jpg` / `assets/ai-inline-1.jpg`, or as `assets/ai-hero.svg` / `assets/ai-inline-1.svg` when using the zero-cost local fallback.
6. Use `stage2_refresh_post` to update the existing Blogger post.
