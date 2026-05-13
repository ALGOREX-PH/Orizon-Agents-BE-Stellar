from ..schemas import BrandSpec, DemoKit, FeatureSpec, PaletteSpec, TypographySpec

POMODORO_KIT = DemoKit(
    kit_id="pomodoro",
    triggers=["pomodoro", "tomato timer", "focus timer", "deep work timer"],
    brand=BrandSpec(
        name="CADENCE·25",
        tagline="A deep-work timer with rituals: cycles, chimes, and a daily tomato counter.",
        audience=["focus seekers", "knowledge workers", "students", "remote workers"],
        keywords=[
            "pomodoro", "focus", "timer", "deep work", "productivity",
            "browser", "notification", "single-file html", "cycles", "ritual",
        ],
    ),
    features=[
        FeatureSpec(
            label="Configurable work / short / long durations",
            detail="Three sliders: Work (15–90 min, default 25), Short break (3–15, default 5), Long break (10–45, default 20).",
        ),
        FeatureSpec(
            label="4-cycle ritual with long-break trigger",
            detail="After every 4 work intervals, the next break is the configured long break. A visible chain of 4 dots tracks progress.",
        ),
        FeatureSpec(
            label="Accurate millisecond timer",
            detail="Drift-free timer using `performance.now()` deltas, not naive `setInterval` counting.",
        ),
        FeatureSpec(
            label="Audio chime + Notification API",
            detail="AudioContext generates a soft 3-tone chime on phase transition. Notification API requests permission and posts a system notification.",
        ),
        FeatureSpec(
            label="Daily tomato counter",
            detail="Persistent count of completed work intervals today (resets at local midnight). Big number front-and-center.",
        ),
        FeatureSpec(
            label="Session history with day grouping",
            detail="Scrollable log of completed intervals (kind + duration + ISO time). Grouped by day, last 14 days kept.",
        ),
        FeatureSpec(
            label="Keyboard shortcuts",
            detail="Space pause/resume, R reset current phase, S skip to next phase, T toggle theme, M mute chime, N toggle notifications.",
        ),
        FeatureSpec(
            label="Dark / light theme + reduced motion",
            detail="Theme toggle persists. Respects `prefers-color-scheme` on first load and `prefers-reduced-motion` for the ring animation.",
        ),
    ],
    palette=PaletteSpec(
        bg="#0E0A1F",
        surface="#181030",
        surface_2="#20183E",
        border="#2E2354",
        text="#F4F0FE",
        muted="#9C92BD",
        primary="#FF9F1C",   # amber — the tomato accent
        accent="#7A5CFF",    # violet — secondary
        danger="#FF4D6D",
    ),
    typography=TypographySpec(
        family_ui="'Inter', system-ui, sans-serif",
        family_display="'Space Mono', 'JetBrains Mono', ui-monospace, monospace",
    ),
    critic_checklist=[
        "Timer is drift-free — verified by reading `performance.now()` deltas, not naive setInterval counters",
        "Three configurable durations (work / short break / long break) with sensible bounds",
        "Cycle counter visibly advances; after 4 work cycles the next break uses the long-break duration",
        "AudioContext chime plays at every phase transition (gated by a mute toggle)",
        "Notification permission is requested on user gesture; notifications fire on phase transition",
        "Daily tomato counter persists in localStorage and resets at local midnight",
        "Session history persists in localStorage (at least the last 14 days)",
        "Settings (durations, theme, mute) persist between reloads",
        "Keyboard shortcuts Space / R / S / T / M / N all wired",
        "Respects prefers-reduced-motion (the progress ring fades instead of animating)",
    ],
    code_gen_addendum="""## POMODORO-SPECIFIC IMPLEMENTATION NOTES

Timer:
- Maintain `phase: 'work'|'short'|'long'`, `phaseStartedAt: ms`, `phaseDurationMs`, `cycle: 0..3`.
- Use a `requestAnimationFrame` render loop that reads `performance.now()` and computes remaining ms. Format as `MM:SS`. This is drift-free.
- On phase end: increment `cycle` (only after a work phase), pick next phase via the 4-cycle rule, fire chime + notification.

Audio:
- `AudioContext`; build a 3-tone chime (e.g. 523Hz → 659Hz → 784Hz over 600ms with gain ramp). Lazily create the context on first user gesture.

Notification:
- Request permission on a "Enable notifications" button (NOT on load). After granted, post `new Notification(title, { body, silent })` at each transition.

Layout:
- Centered card: big circular progress ring around the MM:SS, kind label (Work / Short break / Long break) above, cycle dots below, primary action button (Start / Pause / Resume) and secondary (Reset, Skip) buttons.
- Settings drawer slides up from the bottom with the three duration sliders and toggles for chime/notifications/theme.
- History tab beside the timer (tabs at the top of the card).

Polish:
- Progress ring is a `<svg circle>` with `stroke-dasharray` animated to fill as time elapses.
- Tomato counter is a single large number with a tiny "🍅" SVG glyph beside it (or an inline tomato SVG — never an emoji image).
- Phase transitions briefly flash the background tint of the next phase.""",
    expected_min_lines=400,
)
