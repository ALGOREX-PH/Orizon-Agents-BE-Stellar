from ..schemas import BrandSpec, DemoKit, FeatureSpec, PaletteSpec, TypographySpec

CALCULATOR_KIT = DemoKit(
    kit_id="calculator",
    triggers=["calculator", "calc app", "scientific calc"],
    brand=BrandSpec(
        name="AURORA·CALC",
        tagline="Scientific calculator with history, memory, and a real keyboard.",
        audience=["engineers", "students", "researchers", "power users"],
        keywords=[
            "calculator", "scientific", "memory", "history", "keyboard",
            "single-file html", "browser", "BODMAS", "parentheses", "copy",
        ],
    ),
    features=[
        FeatureSpec(
            label="Standard + scientific operators",
            detail="+ − × ÷ plus sin, cos, tan, asin, acos, atan, log10, ln, √, x², x^y, π, e, % and parentheses.",
        ),
        FeatureSpec(
            label="BODMAS expression evaluator",
            detail="Tokenize → shunting-yard → RPN evaluator (no `eval`!). Supports nested parentheses and unary minus.",
        ),
        FeatureSpec(
            label="Memory bank (M+ / M− / MR / MC / MS)",
            detail="Visible memory slot with badge when non-zero; full set of memory operations on the keypad.",
        ),
        FeatureSpec(
            label="Scrollable history pane",
            detail="Last 20 expressions with their results; click an entry to recall it into the input. Persists to localStorage.",
        ),
        FeatureSpec(
            label="Full keyboard binding",
            detail="Digits, operators, Enter (=), Backspace, Esc (AC), parentheses, decimal point. Tab cycles focus through buttons.",
        ),
        FeatureSpec(
            label="Robust error handling",
            detail="Division by zero shows 'Error · /0', invalid input shows 'Error · syntax'. Esc clears the error state.",
        ),
        FeatureSpec(
            label="Theme toggle (dark / light)",
            detail="Persisted theme preference; respects `prefers-color-scheme` on first load.",
        ),
        FeatureSpec(
            label="Copy-to-clipboard result",
            detail="Long-press or click the result to copy. Brief toast confirms.",
        ),
    ],
    palette=PaletteSpec(
        bg="#0A0613",
        surface="#141022",
        surface_2="#1D1830",
        border="#2C2548",
        text="#F2EEFB",
        muted="#8B83A8",
        primary="#7A5CFF",   # violet
        accent="#00FFD1",    # cyan
        danger="#FF4D6D",
    ),
    typography=TypographySpec(
        family_ui="'Inter', system-ui, sans-serif",
        family_display="'JetBrains Mono', ui-monospace, monospace",
    ),
    critic_checklist=[
        "All 4 standard operators (+, −, ×, ÷) and at least 6 scientific operators",
        "Parentheses with proper precedence — '2*(3+4)' returns 14",
        "Memory buttons M+, M−, MR, MC, MS all visible and wired",
        "History pane shows at least the last 10 expressions and persists in localStorage",
        "Full keyboard binding (digits, ops, Enter, Backspace, Esc, parens)",
        "Division by zero shows a friendly error string, not 'Infinity' or 'NaN'",
        "No use of JavaScript `eval()` — use a real tokenize-evaluate pipeline",
        "Copy result to clipboard via the Async Clipboard API with a toast confirmation",
        "Respects prefers-reduced-motion (no button-press flashes)",
        "Theme toggle persists in localStorage",
    ],
    code_gen_addendum="""## CALCULATOR-SPECIFIC IMPLEMENTATION NOTES

Architecture:
- `tokenize(src) → Token[]` — split into numbers, operators, parens, function names.
- `toRPN(tokens) → Token[]` — shunting-yard with precedence: function/unary > ^ > × ÷ > + −, right-assoc for ^.
- `evalRPN(rpn) → number | Error` — stack-based; functions pop 1, binary pop 2.
- Never call `eval()`. If a token is invalid, return `{ error: 'syntax' }`.

Layout (responsive grid):
- Display panel on top with the current expression (smaller) above the live result (larger).
- A 5-row keypad below: row 0 = scientific (sin cos tan log ln √), row 1 = (memory M+, M-, MR, MC), row 2-4 = digits + ops + parens. Decimal + sign-toggle in the bottom row.
- History pane is a collapsible right rail on desktop, a bottom drawer on mobile.

Keyboard:
- Bind `keydown` on `window`. Map every digit, `.`, `+`, `-`, `*`, `/`, `(`, `)`, Enter, Backspace, Esc.
- Show a transient highlight on the visual button when its key is pressed.

Polish:
- Use `Intl.NumberFormat` for digit grouping when display width allows.
- Auto-shrink display font (clamp from 48px down to 24px) as expression grows.
- Memory badge appears in the top-right when memory is non-zero.""",
    expected_min_lines=500,
)
