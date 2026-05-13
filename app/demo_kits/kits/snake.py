from ..schemas import BrandSpec, DemoKit, FeatureSpec, PaletteSpec, TypographySpec

SNAKE_KIT = DemoKit(
    kit_id="snake",
    triggers=["snake game", "snake", "viper game"],
    brand=BrandSpec(
        name="VIPER·GRID",
        tagline="Snake reborn with neon trails, bonus prey, and a 5-deep leaderboard.",
        audience=["casual gamers", "lunch-break players", "nostalgia seekers"],
        keywords=[
            "snake", "arcade", "html5", "canvas", "leaderboard",
            "single-file", "keyboard", "swipe", "browser game", "retro",
        ],
    ),
    features=[
        FeatureSpec(
            label="Grid + growing-body collision",
            detail="20×20 grid (configurable). Snake grows by one segment per food, dies on self-collision.",
        ),
        FeatureSpec(
            label="4 selectable speed levels",
            detail="slow (200ms tick), normal (130ms), fast (90ms), insane (55ms). Selectable from start screen and during pause.",
        ),
        FeatureSpec(
            label="Wraparound toggle",
            detail="Walls kill by default; toggle to wrap-around mode where the snake reappears on the opposite edge.",
        ),
        FeatureSpec(
            label="Two food types",
            detail="Green pellet (+1 length, +10 score). Magenta bonus pellet appears every ~10s for 5s only (+3 length, +50 score).",
        ),
        FeatureSpec(
            label="Top-5 leaderboard with names",
            detail="Game-over prompts for 3-char initials; saves to localStorage with score + length + level + ISO timestamp.",
        ),
        FeatureSpec(
            label="Keyboard + swipe controls",
            detail="Arrow keys + WASD on desktop. Swipe gestures on touch. Snake can't reverse direction in a single tick.",
        ),
        FeatureSpec(
            label="Pause overlay + HUD",
            detail="Space to pause. HUD shows score, length, best-of-session, FPS-style speed indicator. Pause overlay covers the grid.",
        ),
        FeatureSpec(
            label="Subtle motion + sound",
            detail="Snake head leaves a 100ms trail. AudioContext beep on eat (different pitch for bonus). Respects prefers-reduced-motion.",
        ),
    ],
    palette=PaletteSpec(
        bg="#040A06",
        surface="#0C1810",
        surface_2="#15281A",
        border="#1F3D27",
        text="#E8F8EE",
        muted="#7AA088",
        primary="#3DFF85",   # neon green
        accent="#00FFD1",    # cyan
        danger="#FF2EC4",    # magenta (bonus food)
    ),
    typography=TypographySpec(
        family_ui="'JetBrains Mono', ui-monospace, monospace",
        family_display="'JetBrains Mono', ui-monospace, monospace",
    ),
    critic_checklist=[
        "Grid renders with a visible faint grid line in --border",
        "Snake direction cannot reverse in a single tick (no instant self-death from one keypress)",
        "Food spawns only on empty cells (no overlap with snake body)",
        "Bonus food appears periodically and disappears after ~5 seconds with a flash",
        "Wall collision kills snake when wrap-around is off; wraps when on",
        "Self-collision always kills",
        "Top-5 leaderboard persists in localStorage and survives reload",
        "All 4 speed levels selectable and tick rate changes accordingly",
        "Pause works mid-game with Space key",
        "Touch swipe registers and changes direction",
    ],
    code_gen_addendum="""## SNAKE-SPECIFIC IMPLEMENTATION NOTES

Use a `<canvas>` for the playfield (~500×500 px = 25px per cell on a 20×20 grid).

State:
- `snake: { x, y }[]` (head at index 0).
- `dir: { x: -1|0|1, y: -1|0|1 }` and `pendingDir` to debounce reversal in one tick.
- `food: { x, y, type: 'normal'|'bonus', expiresAt? }`.
- `score`, `length`, `level`, `mode: 'walls'|'wrap'`, `paused`, `over`.

Loop:
- `setInterval(tick, tickMs)` where `tickMs` is `{slow:200, normal:130, fast:90, insane:55}[level]`. Reset on level change.
- Each tick: apply `pendingDir`, advance head, check wall/self collision, check food collision, render.

Bonus food spawner:
- Every 8–12 seconds, drop a bonus pellet for 5s. Use a separate timer + cleanup.

Controls:
- Window `keydown`: ArrowLeft/A → {-1,0}; ArrowRight/D → {1,0}; ArrowUp/W → {0,-1}; ArrowDown/S → {0,1}; Space → toggle pause.
- Touch: track first touch on the canvas; on touchend, compute dx/dy; whichever has the larger absolute value picks the axis; sign picks the direction.

Polish:
- Snake head has a slight gradient (lighter near direction of motion).
- On eat: brief radial flash at the eaten cell. Bonus eat = magenta flash + double-frequency beep.
- Game over: dim the playfield, show a score card with "name?" 3-char input → leaderboard.""",
    expected_min_lines=450,
    artifact_path="snake.html",
)
