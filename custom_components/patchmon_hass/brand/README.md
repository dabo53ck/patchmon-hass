# Brand assets

The mark: a house (Home Assistant) holding a "Pac" shape with a dark eye, a nod
to the PatchMon logo, in Home Assistant blue.
It is an original drawing, not the PatchMon logo itself.

| Light | Dark | |
| --- | --- | --- |
| `icon.png` (256) / `icon@2x.png` (512) | `dark_icon.png` / `dark_icon@2x.png` | Square app icon |
| `logo.png` / `logo@2x.png` | `dark_logo.png` / `dark_logo@2x.png` | Wordmark ("patchmon-hass" + "Your homelab's updates in Home Assistant") |

Colours: house `#1B2B45` (dark variant `#33507A`, so it stays visible on dark
backgrounds), Pac `#18BCF2`, eye `#1B2B45` in both variants (in the dark variant
darker than the house).

Each PNG has a matching `*.svg` source. Home Assistant loads these directly
from this folder (no `home-assistant/brands` PR needed) and picks the `dark_*`
variant in dark mode.

The wordmark text in the logo SVGs is already converted to outlines
(Liberation Sans Bold), so it renders the same everywhere. The descriptor is
sized so that its left and right edges line up with "patchmon-hass".

The PNGs are committed, rendered from the SVGs with
[CairoSVG](https://cairosvg.org/). Regenerate after editing an SVG:

```sh
python -c "
import cairosvg
for v in ('icon', 'dark_icon'):
    cairosvg.svg2png(url=f'{v}.svg', write_to=f'{v}.png', output_width=256, output_height=256)
    cairosvg.svg2png(url=f'{v}.svg', write_to=f'{v}@2x.png', output_width=512, output_height=512)
for v in ('logo', 'dark_logo'):
    cairosvg.svg2png(url=f'{v}.svg', write_to=f'{v}.png', output_height=256)
    cairosvg.svg2png(url=f'{v}.svg', write_to=f'{v}@2x.png', output_height=512)
"
```
