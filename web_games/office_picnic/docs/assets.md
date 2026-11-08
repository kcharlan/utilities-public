# Generated assets

All four images were generated with the built-in ImageGen tool in this chat. Production copies are in `dist/assets/`; the game has no image-generation dependency.

## Key art — `dist/assets/key-art.png`

Generated first, before district geometry. Prompt:

> Use case: stylized-concept. Asset: wide key art for a quiet browser game called Office Picnic (no lettering). A tiny ivory paper airplane just thrown from an open window on the fortieth floor of an office tower at 5:01 pm, floating above a city toward a small distant green park and picnic tables. Side-on cinematic city panorama at dusk, warm honey illuminated office windows, cool dusty blue and violet shadows, soft apricot horizon. Beautiful restrained painted gouache illustration, architectural shapes, layered atmospheric depth, readable silhouettes, calm wistful after-work mood, small plane prominent against open sky. Landscape 1536x1024 composition. No typography, logos, watermark, UI or borders.

Inspected the generated image. The key art supplies the title screen; in-game backgrounds are Canvas code. `palette.json` records sampled shadow, sky and warm colors plus supporting derived tones. Extraction used macOS `sips` to average down to a 24×16 BMP, then Node read RGB pixels at the documented coordinates. The actual painting is the palette reference, rather than a preset chosen before generation.

## Plane — `dist/assets/plane-sheet.png`

Prompt:

> Use case: stylized-concept. Production sprite sheet for paper airplane browser game. TRANSPARENT background. Exact 1024 by 1024 square, 2 columns by 2 rows of equal 512px cells. Each cell has one centered ivory folded paper airplane, sharp readable silhouette, points RIGHT, horizontal level side view, same pivot and scale in every cell, plane confined to center 360 by 200 pixels with generous transparent gutters. Top-left relaxed glide, top-right wings slightly flexed, bottom-left paper wings strained, bottom-right softly crumpled wingtips for stall. Restrained painted gouache edges with clean solid ivory faces and cool muted violet fold shadows, warm peach edge lighting, no outlines around cells, no grid lines, no labels, no text, no drop shadow, no other objects. All four planes point right and are level: runtime rotates them.

Actual tool output is **1254×1254**, with a **2×2 grid of 627×627 cells**, rather than the requested resolution. The renderer uses the verified actual dimensions. The four cells are visibly separated, transparent, and aligned closely enough for glide/strain/stall state changes. No cropping or destructive image editing was needed. The code rotates the plane for pitch.

## Pigeon — `dist/assets/pigeon-sheet.png`

Prompt:

> Use case: stylized-concept. Production pigeon animation sprite sheet, genuinely TRANSPARENT background. Exact 1024x1024 square with 2 columns and 2 rows of equal 512px cells. Four same-sized centered pigeons facing LEFT, side view, each within central 340x340 pixels with wide transparent gutters and same body pivot. Reading row-major: wings high, wings half down, wings low, wings half up. Cool slate blue and violet pigeon body, pale grey wing edge, tiny warm peach beak. Painterly gouache but bold clean recognizable silhouette at small screen size. Uniform bird body proportions, no perspective shifts. No lettering, grid lines, background, shadows, extra birds or objects.

Actual output is also **1254×1254**, **2×2 cells of 627×627**. Inspected silhouettes, frame separation and alpha. Code uses that grid for four flap frames. The physical collision shape is intentionally more forgiving than the visible wings. Reduced motion freezes the decorative wing animation; pigeon body movement remains an essential obstacle motion.

Image dimensions/alpha are checked by the Node suite, and browser verification checks actual decoding. Air effects, skyline, park, picnic table and potato salad are code-drawn.

## Window washer — `dist/assets/washer-v1.png`

Generated as a compact gouache illustration, then edited with ImageGen to remove the remaining background/glow while preserving the worker, squeegee, bucket, harness, silver guard rails and ochre deck. The brief requested a recognizable adult with articulated limbs, a visible face, yellow hardhat and blue overalls; no giant enclosing cage, net, building, text or long suspension cables. Dusk peach lighting and blue-violet shadows match the key art.

Actual asset is 1536×1024 RGBA. A PNG alpha inspection confirmed zero-alpha background/openings; browser inspection confirmed clean compositing. Code draws the two suspension cables and maps the illustration into the authored platform rectangle using the same horizontal/vertical projection as collision geometry. Portrait therefore shares the world's nonuniform projection. A runtime rendering regression checks desktop, portrait and landscape bounds. No skeleton/keyhole figure or mesh remains.
