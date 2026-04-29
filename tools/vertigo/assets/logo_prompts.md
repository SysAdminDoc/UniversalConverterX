# Vertigo Logo — Generation Prompts

**Project:** Vertigo — a premium desktop studio that turns raw horizontal footage into polished 9:16 vertical for YouTube Shorts, TikTok, and Instagram Reels. From the Latin *vertere*, "to turn." The brand leans into a cinematic spin / rotation / vertical-fall metaphor: the act of *turning* footage from wide to tall, with a nod to Hitchcock-era graphic design language (concentric circles, dolly-zoom perspective, mauve-to-pink gradients on deep charcoal). Dark mode first, mauve→pink accent (`#cba6f7` → `#f5c2e7`), sharp geometric lines, cinematic.

Use these five prompts with your preferred generative image model (Midjourney, DALL·E, Stable Diffusion, Ideogram, Recraft). Pick one to become the primary mark.

---

## 1. Minimal icon (16px–128px favicons, toolbar)
> Minimalist flat icon for a vertical-video tool called **Vertigo**. A single geometric glyph: a 9:16 vertical frame containing a tight spiral that winds inward toward the bottom, suggesting rotation and vertical descent. Solid mauve `#cba6f7` on a transparent background. Pixel-grid-aligned, no shading, no gradients, crisp at 16 × 16 pixels. SVG-friendly construction with a maximum of 2 stroke weights. Generous padding.

## 2. App icon (Chrome Web Store, macOS dock, Windows taskbar, Android adaptive)
> Modern SaaS app icon, 512 × 512, rounded-square container with 22 % corner radius. Center mark: a tall 9:16 vertical frame with a dolly-zoom spiral inside — concentric rings compressing toward a single point near the bottom, suggesting the cinematic *vertigo effect* where depth collapses. Mauve-to-pink radial gradient (`#cba6f7` outer → `#f5c2e7` inner) glowing from within. Deep charcoal background `#1e1e2e`. Subtle inner glow, soft drop shadow, no text. One plane of depth. Premium, confident, cinematic.

## 3. Wordmark (README headers, splash, website hero)
> Horizontal wordmark for **VERTIGO**, set in an uppercase geometric sans-serif (Space Grotesk / Satoshi / custom). Seven letters, near-white `#cdd6f4`, tight letter-spacing with razor-sharp kerning. A thin mauve `#cba6f7` → pink `#f5c2e7` underline begins at the foot of the **V** and extends past the **O**, terminating in a tiny vertical 9:16 frame glyph containing a small play triangle. Dark background `#11111b`. Subtle warm glow under the underline. Editorial, premium, Hitchcock-era confident.

## 4. Emblem (README header art, installer splash, About dialog)
> Detailed circular emblem badge, 1024 × 1024, dark-mode aesthetic. A 9:16 vertical frame at the center of a concentric-ring spiral — the Saul-Bass / Vertigo poster motif translated into 2026 brand language. Thin mauve rings orbit the frame, fading outward; inside the frame, a tiny play triangle glows. Ring around the emblem carries four small platform glyphs at cardinal points — YouTube Shorts triangle, TikTok note, Instagram camera, square 1:1. Gradient plate from `#181825` to black, mauve `#cba6f7` highlight rim, pink `#f5c2e7` particles. No text inside the emblem. Luxury tech badge with gentle film grain.

## 5. Abstract (marketing, social, conceptual)
> Abstract conceptual art representing horizontal-to-vertical video transformation. A wide 16:9 plane of cinematic footage tumbles and rotates in space, caught mid-spiral as it compresses into a tall glowing 9:16 pillar that stands upright. Long motion-streaks trail the fold. Deep matte black background `#11111b`. Mauve and pink volumetric light `#cba6f7` / `#f5c2e7` pouring through the rotation. High contrast, cinematic depth, hint of dolly-zoom distortion at the edges. No text. Premium editorial poster style. 16:9 composition with the vertical pillar anchored center, slightly right.

---

## After selection — integration follow-up

Generate the primary mark, then use this prompt with your coding assistant:

> I've generated the final logo for Vertigo. Please integrate it: (1) save as `assets/icon.svg` and `assets/icon.png` in the repo root plus 16/32/48/128/256/512 size PNG variants; (2) regenerate `assets/icon.ico` as a multi-resolution Windows icon; (3) reference the emblem or wordmark in `README.md` as a centered header image above the badges; (4) wire it into PyQt6 via the existing `ui/assets.icon_path()` resolver — no code change needed if the filename stays `icon.png` / `icon.ico`; (5) regenerate `assets/wordmark.svg` to match the new brand; (6) update `.github/workflows/build.yml` if any artifact names reference old assets; (7) embed the 16 × 16 favicon as a base64 data URI in any future web artifacts.

## Palette reference

| Role | Hex |
| --- | --- |
| Accent primary (mauve) | `#cba6f7` |
| Accent secondary (pink) | `#f5c2e7` |
| Background base | `#1e1e2e` |
| Background crust | `#11111b` |
| Text | `#cdd6f4` |
| Surface | `#313244` |
