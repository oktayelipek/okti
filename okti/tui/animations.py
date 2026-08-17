"""Animations, ASCII art, mascots, and themes for an expressive TUI experience."""

from __future__ import annotations

import random
import time

from rich.text import Text
from textual.widgets import Static

BRAILLE_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
CYBER_SPINNER = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰", "▱▰▰▰▰", "▱▱▰▰▰", "▱▱▱▰▰", "▱▱▱▱▰"]
PULSE_DOTS = ["●○○○", "○●○○", "○○●○", "○○○●", "○○●○", "○●○○"]

MASCOTS = {
    "idle": [
        "(•‿•) Ready to build",
        "( ˘ ³˘) Standing by",
        "(^-^*) What are we coding today?",
        "(^o^) Systems operational",
    ],
    "thinking": [
        "(◕‿◕)⚡ Cooking solution...",
        "( ಠ_ಠ ) Analyzing codebase...",
        "(¬‿¬) Formulating plan...",
        "(⊙_⊙) Scanning possibilities...",
    ],
    "tool": [
        "(ง'̀-'́)ง Running {tool}...",
        "(•_•)ᕗ Tinkering with files...",
        "ᕙ(⇀‸↼‶)ᕗ Executing command...",
        "(~˘▾˘)~ Applying changes...",
    ],
    "success": [
        "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧ Done!",
        "(★‿★) Nailed it!",
        "(づ｡◕‿‿◕｡)づ All good!",
        "(•̀ᴗ•́)و Quality code delivered",
    ],
    "error": [
        "(╯°□°)╯︵ ┻━┻ Error occurred!",
        "(ノಠ益ಠ)ノ Something went wrong",
        "(⊙_☉) Permission denied or blocked",
    ],
}

DEV_QUOTES = [
    "“Simplicity is prerequisite for reliability.” — Edsger W. Dijkstra",
    "“First, solve the problem. Then, write the code.” — John Johnson",
    "“Make it work, make it right, make it fast.” — Kent Beck",
    "“Before software can be reusable it first has to be usable.” — Ralph Johnson",
    "“Code is like humor. When you have to explain it, it’s bad.” — Cory House",
    "“Fix the cause, not the symptom.” — Steve Maguire",
    "“Deleted code is debugged code.” — Jeff Sickel",
    "“There are only two hard things in Computer Science: cache invalidation and naming things.” — Phil Karlton",
]

ASCII_LOGO = r"""
   ██████╗  ██╗  ██╗ ████████╗ ██╗
  ██╔═══██╗ ██║ ██╔╝ ╚══██╔══╝ ██║
  ██║   ██║ █████╔╝     ██║    ██║
  ██║   ██║ ██╔═██╗     ██║    ██║
  ╚██████╔╝ ██║  ██╗    ██║    ██║
   ╚═════╝  ╚═╝  ╚═╝    ╚═╝    ╚═╝
       ░▒▓█ NEURAL CODE INTERFACE █▓▒░
"""

# Cyberpunk neon palette: hot pink, cyan, electric purple, acid yellow, magenta
GRADIENT_PALETTES = [
    ["#ff2a6d", "#d900ff", "#05d9e8", "#00f0ff", "#f9f871", "#ff006e"],
    ["#d900ff", "#05d9e8", "#00f0ff", "#f9f871", "#ff006e", "#ff2a6d"],
    ["#05d9e8", "#00f0ff", "#f9f871", "#ff006e", "#ff2a6d", "#d900ff"],
    ["#00f0ff", "#f9f871", "#ff006e", "#ff2a6d", "#d900ff", "#05d9e8"],
    ["#f9f871", "#ff006e", "#ff2a6d", "#d900ff", "#05d9e8", "#00f0ff"],
    ["#ff006e", "#ff2a6d", "#d900ff", "#05d9e8", "#00f0ff", "#f9f871"],
]


class AnimatedAsciiBanner(Static):
    """Animated rainbow/neon wave ASCII logo banner with live shimmering effect."""

    def __init__(self, provider_name: str = "", model_name: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.model_name = model_name
        self._frame = 0
        self._quote = get_random_quote()

    def on_mount(self) -> None:
        self.set_interval(0.12, self._tick)

    def _tick(self) -> None:
        self._frame += 1
        self.refresh()

    def render(self) -> Text:
        # Clean palette: soft purple accent, muted text, no animation shimmer.
        # Keep the ASCII logo — draw it in a single accent color for a clean,
        # brand-recognizable header (no rainbow shimmer).
        ACCENT = "#cba6f7"
        TEXT = "#cdd6f4"
        MUTED = "#6c7086"

        out = Text()
        out.append("\n")
        # Only the block letters, not the tagline row from ASCII_LOGO
        lines = ASCII_LOGO.strip().splitlines()
        for line in lines:
            if "NEURAL CODE" in line:
                continue  # drop the old cyberpunk tagline row
            out.append(" " + line + "\n", style=f"bold {ACCENT}")
        out.append("\n")
        out.append("  Agentic coding for the terminal.\n\n", style=MUTED)

        if self.model_name:
            label = self.model_name
            if self.provider_name:
                label = f"{self.provider_name} / {self.model_name}"
            out.append("  Model: ", style=MUTED)
            out.append(f"{label}\n", style=TEXT)
        out.append(f"  {self._quote}\n\n", style=f"italic {MUTED}")
        out.append("  Type a message, or press ", style=MUTED)
        out.append("/", style=f"bold {ACCENT}")
        out.append(" for commands.\n", style=MUTED)
        return out

class ThinkingIndicator(Static):
    """Live pulsing spinner showing current model and elapsed thinking time."""

    def __init__(self, model_name: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.model_name = model_name
        self._frame = 0
        self._start_time = time.time()

    def on_mount(self) -> None:
        self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self._frame += 1
        self.refresh()

    def render(self) -> Text:
        spinner = BRAILLE_SPINNER[self._frame % len(BRAILLE_SPINNER)]
        elapsed = time.time() - self._start_time

        out = Text()
        out.append("\n ⚡ ", style="bold yellow")
        out.append("Thinking", style="bold cyan")
        if self.model_name:
            out.append(f" with {self.model_name}", style="bold white")
        out.append(f"... {spinner} ", style="bold magenta")
        out.append(f"({elapsed:.1f}s)\n", style="dim")
        return out


THEMES = {
    "default": """
    Screen { background: #0f111a; color: #abb2bf; }
    #sidebar { background: #161822; border-right: tall #212534; }
    #dock-panel { background: #161822; border-left: tall #212534; }
    #input-bar { border: tall #61afef; background: #1a1c29; }
    .user-message { background: #1e2233; color: #e5c07b; border-left: thick #61afef; }
    .assistant-message { background: #181a24; border-left: thick #98c379; }
    """,
    "synthwave": """
    Screen { background: #18122B; color: #E1E8EB; }
    #tool-dock { background: #251B3E; border-bottom: solid #F472B6; }
    #input-bar { border: round #F472B6; background: #393053; }
    .user-message { background: #393053; color: #F472B6; border-left: thick #F472B6; }
    .assistant-message { background: #2A2438; border-left: thick #38BDF8; }
    """,
    "matrix": """
    Screen { background: #050d08; color: #00FF66; }
    #tool-dock { background: #0a180e; border-bottom: solid #00aa44; }
    #input-bar { border: round #00FF66; background: #0d2214; }
    .user-message { background: #0f2b19; color: #00ff88; border-left: thick #00FF66; }
    .assistant-message { background: #08160c; border-left: thick #33ff99; }
    """,
    "cyberpunk": """
    Screen { background: #090A0F; color: #FCEE09; }
    #tool-dock { background: #121526; border-bottom: solid #00F0FF; }
    #input-bar { border: round #00F0FF; background: #1E2238; }
    .user-message { background: #241D3B; color: #FCEE09; border-left: thick #00F0FF; }
    .assistant-message { background: #121526; border-left: thick #FF003C; }
    """,
    "nord": """
    Screen { background: #2E3440; color: #D8DEE9; }
    #tool-dock { background: #3B4252; border-bottom: solid #88C0D0; }
    #input-bar { border: round #88C0D0; background: #434C5E; }
    .user-message { background: #434C5E; color: #ECEFF4; border-left: thick #88C0D0; }
    .assistant-message { background: #3B4252; border-left: thick #A3BE8C; }
    """,
}


def get_random_mascot(state: str, tool_name: str = "") -> str:
    """Get a random mascot expression for the given state."""
    options = MASCOTS.get(state, MASCOTS["idle"])
    template = random.choice(options)
    return template.format(tool=tool_name) if "{tool}" in template else template


def get_random_quote() -> str:
    """Return a random inspirational or funny dev quote."""
    return random.choice(DEV_QUOTES)


class Speedometer:
    """Tracks token generation rate and elapsed time."""

    def __init__(self):
        self.start_time: float | None = None
        self.total_tokens: int = 0

    def start(self) -> None:
        self.start_time = time.monotonic()
        self.total_tokens = 0

    def add_tokens(self, count: int) -> None:
        self.total_tokens += count

    def speed(self) -> float:
        if not self.start_time:
            return 0.0
        elapsed = time.monotonic() - self.start_time
        if elapsed < 0.1:
            return 0.0
        return self.total_tokens / elapsed

    def elapsed(self) -> float:
        if not self.start_time:
            return 0.0
        return time.monotonic() - self.start_time
