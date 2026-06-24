# Image Rules

Korea Easy Guide uses AI-generated raster images for published posts. Local SVG covers are fallback assets only.

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
- Save as compressed JPG around 1200x675 before embedding in Blogger.

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
4. Convert to JPG:

```bash
sips -s format jpeg -s formatOptions 78 -z 675 1200 source.png --out ai-hero.jpg
```

5. Reference it in article HTML as `assets/ai-hero.jpg` or `assets/ai-inline-1.jpg`.
6. Use `stage2_refresh_post` to update the existing Blogger post.
