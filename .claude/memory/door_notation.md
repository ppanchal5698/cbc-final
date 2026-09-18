# Door Size Notation

Four-digit shorthand. **First two digits = width, second two = height**, each read as
feet-and-inches.

| Shorthand | Width | Height |
|---|---|---|
| 3070 | 3'-0" | 7'-0" |
| 3670 | 3'-6" (42") | 7'-0" |
| 2868 | 2'-8" | 6'-8" |
| 4080 | 4'-0" | 8'-0" |

The notation is applied consistently across all CBC quotes.

## But: not every bid set uses it
Architectural schedules frequently state sizes **explicitly** instead — the Dutch Bros
fixture writes 3' - 0" and 7' - 0" in separate schedule columns. Retail sheets often
print bare inches (`36"` × `84"`). The extractor must handle **all three** forms and
normalise to width / height strings plus the 4-digit size code when it is derivable.

Never infer a size that is not on the drawing. A missing size is a review flag, not a default.

See [handing_codes](handing_codes.md), [frame_depths](frame_depths.md).
