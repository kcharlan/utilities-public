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

Image dimensions/alpha are checked by the Node suite, and browser verification checks actual decoding. Air effects and skyline are code-drawn; the park uses the painted picnic assets described below.

The scenery uses the key art's dusk palette: warm horizon bands, hazy gradient skyline washes and lit windows lead into painted foreground buildings and park foliage. The solid roof edge stays crisp. Sky, building and tree washes, windows, and seeded paper grain are rendered to offscreen canvases on resize; the grain is composited beneath world labels. The caches are reused during flight and the display pixel ratio is capped at two.

## Window washer — `dist/assets/washer-v1.png`

Generated as a compact gouache illustration, then edited with ImageGen to remove the remaining background/glow while preserving the worker, squeegee, bucket, harness, silver guard rails and ochre deck. The brief requested a recognizable adult with articulated limbs, a visible face, yellow hardhat and blue overalls; no giant enclosing cage, net, building, text or long suspension cables. Dusk peach lighting and blue-violet shadows match the key art.

Actual asset is 1536×1024 RGBA. A PNG alpha inspection confirmed zero-alpha background/openings; browser inspection confirmed clean compositing. Code draws the two suspension cables and maps the illustration into the authored platform rectangle using the same horizontal/vertical projection as collision geometry. Portrait therefore shares the world's nonuniform projection. A runtime rendering regression checks desktop, portrait and landscape bounds. No skeleton/keyhole figure or mesh remains.

## Picnic, time pickup and launch sprites

The seven assets below use the built-in ImageGen tool, with `key-art.png`, `washer-v1.png`, and (for the six later assets) the accepted people sheet as style references. The shared style instruction was:

> Restrained painted gouache illustration, soft brush edges, at most fine dark linework as on a storybook illustration, no thick cartoon outline, dusk light: warm peach rim light from the horizon side, cool blue-violet shadows, muted palette matching a honey-and-violet city at dusk, clean readable silhouette at small size, genuinely transparent background, no text, no logos, no watermark, no ground shadow, nothing cropped.

Raw images are assembled with `scripts/assemble-sheet.mjs`, which separates subjects, discards small disconnected specks, uniformly downscales when necessary, aligns and optionally mirrors them. It does not upscale, repaint or recolour. For the people, the prior retained raw sheet was the starting point specified in the amended plan and counts as attempt one. All dimensions below are production pixels. `npm run assets` prints per-cell metrics; the table records ranges over cells. Transparent share uses alpha ≤8, border uses alpha >8, matte uses semi-transparent pixels, and the palette values use alpha ≥248. Single-image border is informational and does not apply to A3. Window is a solid building corner and is not a cutout.

| Asset | Attempts; prompt subject | Dimensions; processing | Clear / border | Matte; vivid any / foreign; black; saturation | A7 texture; content heights |
| --- | --- | --- | --- | --- | --- |
| People | 1; four invented office colleagues in relaxed and cheering rows, matching identity and foot line, natural hands and visible faces. | 2048×1024; assemble 4×2, 512 px cells, mirror | 78.1–82.4% / 0% | 0%; 0 / 0%; ≤0.015%; 0.274–0.368 | 0.0319–0.0682; 412–430 px |
| Table | 1; long wooden picnic table, cream-and-rose checked cloth, plates, cups, pitcher and empty centre, side view. | 1800×575; trim and pad, then `sips` downscale from 2203×704 | 56.6% / 4.32% | 0%; 0.01 / 0%; 0%; 0.374 | 0.0940; 553 px |
| Bowl | 1; two separated matching ceramic potato-salad bowls, intact and indented with splash, same baseline. | 2048×1024; assemble 2×1, 1024 px cells | 76.3–76.9% / 0% | ≤0.12%; ≤0.01 / 0%; 0%; 0.328–0.340 | 0.0742–0.0751; 523–613 px |
| Props | 2; cooler, blanket with basket, peach/violet triangular bunting, wide gaps. Second prompt requested visible mottled brush marks on each flag after the first bunting failed A7 (0.0172). | 2304×768; assemble 3×1, 768 px cells, centre and foot alignment off | 81.2–93.8% / 0% | 0%; 0 / 0%; 0%; 0.245–0.373 | 0.0333–0.0801; 200–336 px |
| Trees | 1; two different full-canopy park trees with trunks, same baseline and wide separation. | 1536×768; assemble 2×1, 768 px cells, centre alignment off | 71.3–73.1% / 0% | 0%; 0 / 0%; 0%; 0.280–0.287 | 0.0613–0.0735; 501–502 px |
| Token | 1; two separated round office wall clocks with paper tags, idle and brighter pulse, same scale and baseline. | 1536×768; assemble 2×1, 768 px cells | 63.1–63.2% / 0% | 0%; 0 / 0%; 0%; 0.226–0.342 | 0.0344–0.0379; 579–580 px |
| Window | 1; office tower corner, open window, warm interior, half-raised blinds, sill plant, no person. | 799×1150; trim and pad, then `sips` downscale from 872×1255 | 19.0% / 16.35% (not a cutout) | 0%; <0.01 / 0%; 0%; 0.361 | 0.0775; 1104 px |

The 96 px content-normalised A7 minimum is 0.0225, half the lowest reference cell. All seven production assets pass the applicable A1–A7 checks. A8 checks flat and gradient controls, an opaque background, a white halo, foreign vivid green and over-vivid orange against the same gates used for assets. The reference values include washer vivid 11.43% in the warm hue range and washer border 11.85%, which is informational for a single image.

Visual review: at game size on sky and park colours and in the finished landing and asset sheet at 1440×900, 844×390 and 390×844, each asset received **yes** for matching the painted reference, consistent lighting, readable silhouette, freedom from artifacts (inspected at full size), and fitting the scene. The clock also received **yes** for reading as time against sky and building. The bowl base remains aligned between frames. The independent browser review confirmed these answers; the full Rush flight is a separate check.

The retained people draft used the earlier prompt: “Use case: illustration-story, game sprite. Input images are style references only. Four columns by two rows sprite sheet, equal cells: four different invented office colleagues full body, standing front slightly left, rolled sleeves, lanyard, cardigan, loosened tie. Same four relaxed holding cup or plate on first row and cheering arms up second row. Natural hands, visible faces, equal scale and foot line. Generous transparent margins in every cell.” Its original style anchor requested “no outlines”; the other six used the amended anchor quoted above. Four raw people generations preceded the amended workflow and are not counted as assembled attempts.

The final subject prompts follow. Except for props, each was preceded by “Use case: illustration-story, game sprite. Three supplied images are style references only.” All were followed by the shared style instruction above:

- Table: “One long wooden picnic table side view with cream-and-rose checked cloth, plates, cups, pitcher and empty centre for a bowl. Isolated, generous transparent margins.”
- Bowl: “Two equal side-by-side cells of the same ceramic bowl of potato salad, undisturbed left, dented with splash right. Same bowl size and baseline; center each full subject with generous transparent margins and clear separation.”
- Props, attempt 2: “Game sprite sheet of three separate subjects left to right: cooler; picnic blanket with basket; a string of triangular peach and violet bunting flags. Wide transparent gaps and margins. Each flag has visible varied brush marks, mottled paint texture and light and shadow, not flat fill. Style references only in supplied images.”
- Trees: “Two clearly separated different park trees, full canopy and trunk, same scale and baseline; wide transparent gap and generous margins.”
- Token: “Two clearly separated small round office wall clocks with paper tags, unmistakably time; left idle and right brighter for pulse, equal scale and baseline, generous transparent margins.”
- Window: “Office tower corner with one open window, warm interior light, blinds half raised, plant on sill, no person. Fully isolated.”

For layout, the manifest records source-relative baseline fractions. The table is 24.5 m high at 140 m wide, placing its visible top near 20 m while its feet meet the 4 m ground horizon. Vertical sprite dimensions use the camera's vertical projection, including portrait approach. The assembler merges substantial components within 3% of source width. Components smaller than 0.5% of the largest may attach to a nearby substantial component but cannot bridge subjects. Uniform area resampling preserves thin detail, and placement uses each resampled alpha centroid with an 8% gutter.
