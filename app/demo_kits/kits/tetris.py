from ..schemas import BrandSpec, DemoKit, FeatureSpec, PaletteSpec, TypographySpec

TETRIS_KIT = DemoKit(
    kit_id="tetris",
    triggers=["tetris", "tetromino", "block stack", "falling blocks"],
    brand=BrandSpec(
        name="NEON·TETRA",
        tagline="Cyber-arcade falling-blocks, reimagined for the browser.",
        audience=["web-3 gamers", "speedrunners", "retro arcade fans"],
        keywords=[
            "tetris", "neon", "arcade", "block puzzle", "browser game",
            "single-file html", "keyboard", "high score", "T-spin", "B2B",
        ],
    ),
    features=[
        FeatureSpec(
            label="7 tetrominos (I, O, T, S, Z, J, L)",
            detail="Standard Tetris piece set with canonical color assignments (cyan, yellow, purple, green, red, blue, orange).",
        ),
        FeatureSpec(
            label="SRS rotation system",
            detail="Super Rotation System with wall kicks for J/L/S/T/Z and I-piece-specific kicks.",
        ),
        FeatureSpec(
            label="Ghost piece + hold queue + next-3 preview",
            detail="Translucent ghost shows landing spot; Hold slot (one swap per drop); right-side panel previews the next 3 pieces.",
        ),
        FeatureSpec(
            label="Modern scoring (T-spin, Back-to-Back, combos)",
            detail="Single/Double/Triple/Tetris scoring + T-spin Mini / T-spin / T-spin Double with Back-to-Back multiplier.",
        ),
        FeatureSpec(
            label="Lock delay + level/speed curve",
            detail="500ms lock delay with 15-move reset cap. Gravity ramps every 10 lines cleared (level up).",
        ),
        FeatureSpec(
            label="Line-clear flash + level-up pulse",
            detail="Cleared rows flash white for 200ms before gravity drops the stack. Level-up triggers a magenta border pulse.",
        ),
        FeatureSpec(
            label="Full keyboard + touch controls",
            detail="Arrow keys move, Space hard-drop, Up/X rotate CW, Z rotate CCW, C hold, P pause, R restart. Swipe gestures on touch.",
        ),
        FeatureSpec(
            label="Pause overlay + game-over screen + high score",
            detail="Modal pause with resume hint. Game-over screen shows score, lines, level, time. Top-3 high scores persist in localStorage.",
        ),
    ],
    palette=PaletteSpec(
        bg="#0B0414",
        surface="#160826",
        surface_2="#1F0E36",
        border="#2A1750",
        text="#F5F0FF",
        muted="#8A78B8",
        primary="#B026FF",   # violet
        accent="#00FFD1",    # cyan
        danger="#FF2EC4",    # magenta
    ),
    typography=TypographySpec(
        family_ui="'Space Grotesk', system-ui, sans-serif",
        family_display="'JetBrains Mono', ui-monospace, monospace",
    ),
    critic_checklist=[
        "All 7 tetromino shapes (I, O, T, S, Z, J, L) defined with canonical colors",
        "SRS rotation with at least basic wall kicks (test by rotating against the right wall)",
        "Ghost piece renders as a translucent outline of the active piece on the floor",
        "Hold queue accepts one swap per drop and resets on lock-down",
        "Next-3 preview panel on the right",
        "Score increments on line clear; T-spin detection adds bonus",
        "Lock delay ~500ms before piece sets — soft-drop does not instantly lock",
        "Level increases every 10 lines and gravity speeds up",
        "Keyboard handlers wired for ArrowLeft/Right/Down, Space, ArrowUp, Z, C, P, R",
        "Pause overlay covers the playfield and stops gravity",
        "High score saves to localStorage under a namespaced key and survives reload",
        "Respects prefers-reduced-motion (flashes simplified, no screen shake)",
    ],
    code_gen_addendum="""## TETRIS-SPECIFIC IMPLEMENTATION NOTES

Build a 10×20 playfield using a `<canvas>` (preferred) or a CSS grid of cells.

Recommended structure:
- A `Piece` factory returning `{ kind, matrix, color }` for I/O/T/S/Z/J/L.
- A `Board` 10×20 matrix initialized to 0; `lockPiece()` writes the active piece's cells.
- A `Game` controller with state: { board, active, hold, queue: Piece[], score, lines, level, combo, b2b, lockTimer, dropTimer, paused, over }.
- A single `requestAnimationFrame` loop reading `performance.now()` for dt; gravity advances on a timer that scales with `level`.
- Pure helpers: `rotate(matrix, dir)`, `collides(board, piece, dx, dy)`, `clearLines(board) → number`, `tspinKind(board, piece, lastMove) → 'none'|'mini'|'full'`.

Renderers:
- Main playfield (a 300×600 canvas works well at 30px per cell).
- A right-side info panel (200px wide) showing: score, lines, level, time, hold slot, next-3 preview, controls help.

Keyboard:
- ArrowLeft/Right repeat at 150ms after a 230ms initial delay (DAS).
- ArrowDown soft drop = 2× gravity; Space = hard drop (lock immediately, +2 per cell).
- ArrowUp or X rotate CW; Z rotate CCW; C hold (one per drop); P pause; R restart after game over.

Touch (mobile):
- Tap = rotate. Horizontal swipe = move. Down swipe = soft drop. Long swipe down = hard drop.

Visual polish:
- Subtle background grid of dots in `--border`. Active piece has a 1px lighter inset highlight. Ghost piece = active piece color at 25% alpha, no fill.
- Line clear: row flashes white for 200ms then rows above fall.
- T-spin / Tetris: brief score popup floats up from the cleared row.""",
    expected_min_lines=700,
    artifact_path="tetris.html",
)
