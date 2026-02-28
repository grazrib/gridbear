"""TailAdmin Theme for GridBear Admin UI.

Faithful port of the TailAdmin design system: brand blue #465FFF,
Outfit font, custom warm gray palette, white/dark sidebar.
Design tokens extracted from https://github.com/TailAdmin/free-nextjs-admin-dashboard.
"""

from pathlib import Path
from typing import Any

from core.interfaces.theme import BaseTheme

PLUGIN_DIR = Path(__file__).resolve().parent


class TailAdminTheme(BaseTheme):
    name = "theme-tailadmin"

    # -- TailAdmin design tokens ----------------------------------------
    # Brand:   #465FFF (brand-500)
    # Gray:    custom warm gray (gray-50 #f9fafb .. gray-950 #0c111d)
    # Success: #12b76a  Error: #f04438  Warning: #f79009  Orange: #fb6514
    # Font:    Outfit, sans-serif
    # Sidebar: white (light) / #1c2434 (dark)
    # ------------------------------------------------------------------

    def get_css_variables(self) -> dict[str, dict[str, str]]:
        return {
            "light": {
                # Surfaces
                "--canvas": "#f1f5f9",
                "--elevated": "#ffffff",
                "--sidebar-bg": "#ffffff",
                "--header-bg": "#ffffff",
                "--card-bg": "#ffffff",
                "--separator": "#e7e7e9",
                # Typography
                "--label-0": "#1a222c",
                "--label-1": "#333a48",
                "--label-2": "#667085",
                "--label-3": "#98a2b3",
                # Fills
                "--fill-1": "#f9fafb",
                "--fill-2": "#f2f4f7",
                "--fill-3": "#eaecf0",
                "--fill-4": "#d0d5dd",
                # Navigation
                "--nav-active-bg": "rgba(70,95,255,0.08)",
                "--nav-hover-bg": "rgba(0,0,0,0.04)",
                "--nav-active-icon": "#465fff",
                # Accent colors
                "--tint-accent": "#465fff",
                "--tint-green": "#12b76a",
                "--tint-orange": "#f79009",
                "--tint-red": "#f04438",
                "--tint-purple": "#7a5af8",
                "--tint-cyan": "#0ba5ec",
                # Inputs
                "--input-bg": "#ffffff",
                "--input-border": "#d0d5dd",
                "--input-focus-border": "#465fff",
                "--input-focus-ring": "rgba(70,95,255,0.12)",
                "--btn-hover": "#3641d5",
                # Mesh (transparent — no gradients in TailAdmin)
                "--mesh-1": "transparent",
                "--mesh-2": "transparent",
                "--mesh-3": "transparent",
                # Status dots
                "--dot-on": "#12b76a",
                "--dot-on-shadow": "rgba(18,183,106,0.3)",
                "--dot-warn": "#f79009",
                "--dot-warn-shadow": "rgba(247,144,9,0.3)",
                "--dot-off": "#d0d5dd",
                "--dot-err": "#f04438",
                "--dot-err-shadow": "rgba(240,68,56,0.3)",
                # Misc
                "--overlay-bg": "rgba(0,0,0,0.30)",
                "--table-hover": "#f9fafb",
                "--pill-green-bg": "rgba(18,183,106,0.10)",
                "--pill-orange-bg": "rgba(247,144,9,0.10)",
                "--icon-accent-bg": "rgba(70,95,255,0.08)",
                "--icon-green-bg": "rgba(18,183,106,0.10)",
                "--icon-orange-bg": "rgba(247,144,9,0.10)",
                "--icon-purple-bg": "rgba(122,90,248,0.10)",
                "--icon-cyan-bg": "rgba(11,165,236,0.10)",
                "--avatar-from": "#465fff",
                "--avatar-to": "#7a5af8",
                "--version-color": "#98a2b3",
                "--shield-color": "rgba(70,95,255,0.35)",
            },
            "dark": {
                # Surfaces — TailAdmin dark uses #1c2434 sidebar, #101828 canvas
                "--canvas": "#101828",
                "--elevated": "#1d2a39",
                "--sidebar-bg": "#1c2434",
                "--header-bg": "#1d2a39",
                "--card-bg": "#1d2a39",
                "--separator": "#2e3a47",
                # Typography
                "--label-0": "#f0f0f0",
                "--label-1": "#dee4ee",
                "--label-2": "#8899a8",
                "--label-3": "#4a5568",
                # Fills
                "--fill-1": "#1d2a39",
                "--fill-2": "#2e3a47",
                "--fill-3": "#3e4a57",
                "--fill-4": "#4a5568",
                # Navigation
                "--nav-active-bg": "rgba(70,95,255,0.15)",
                "--nav-hover-bg": "rgba(255,255,255,0.04)",
                "--nav-active-icon": "#6e8eff",
                # Accent colors
                "--tint-accent": "#6e8eff",
                "--tint-green": "#34d399",
                "--tint-orange": "#fbbf24",
                "--tint-red": "#fb7185",
                "--tint-purple": "#a78bfa",
                "--tint-cyan": "#67e8f9",
                # Inputs
                "--input-bg": "#1d2a39",
                "--input-border": "#2e3a47",
                "--input-focus-border": "#6e8eff",
                "--input-focus-ring": "rgba(110,142,255,0.20)",
                "--btn-hover": "#5a7aff",
                # Mesh
                "--mesh-1": "transparent",
                "--mesh-2": "transparent",
                "--mesh-3": "transparent",
                # Status dots
                "--dot-on": "#34d399",
                "--dot-on-shadow": "rgba(52,211,153,0.3)",
                "--dot-warn": "#fbbf24",
                "--dot-warn-shadow": "rgba(251,191,36,0.3)",
                "--dot-off": "#3e4a57",
                "--dot-err": "#fb7185",
                "--dot-err-shadow": "rgba(251,113,133,0.3)",
                # Misc
                "--overlay-bg": "rgba(0,0,0,0.55)",
                "--table-hover": "rgba(255,255,255,0.03)",
                "--pill-green-bg": "rgba(52,211,153,0.15)",
                "--pill-orange-bg": "rgba(251,191,36,0.15)",
                "--icon-accent-bg": "rgba(110,142,255,0.15)",
                "--icon-green-bg": "rgba(52,211,153,0.15)",
                "--icon-orange-bg": "rgba(251,191,36,0.15)",
                "--icon-purple-bg": "rgba(167,139,250,0.15)",
                "--icon-cyan-bg": "rgba(103,232,249,0.15)",
                "--avatar-from": "#6e8eff",
                "--avatar-to": "#a78bfa",
                "--version-color": "#4a5568",
                "--shield-color": "rgba(110,142,255,0.35)",
            },
        }

    def get_tailwind_config(self) -> dict[str, Any]:
        return {
            "borderRadius": {
                "ios": "8px",
                "ios-lg": "10px",
                "ios-xl": "12px",
            },
            "colors": {
                "nordic": {
                    "50": "#f2f7ff",
                    "100": "#e1eaff",
                    "200": "#c0d0ff",
                    "300": "#93abff",
                    "400": "#6e8eff",
                    "500": "#465fff",
                    "600": "#3641d5",
                    "700": "#2a32a8",
                    "800": "#212880",
                    "900": "#1c2260",
                    "950": "#161950",
                },
                "void": {
                    "50": "#f9fafb",
                    "100": "#f2f4f7",
                    "200": "#eaecf0",
                    "300": "#d0d5dd",
                    "400": "#98a2b3",
                    "500": "#667085",
                    "600": "#475467",
                    "700": "#344054",
                    "800": "#1d2939",
                    "900": "#101828",
                    "950": "#0c111d",
                },
                "ember": {
                    "400": "#fbbf24",
                    "500": "#f79009",
                    "600": "#dc6803",
                },
                "frost": {
                    "400": "#36bffa",
                    "500": "#0ba5ec",
                    "600": "#0086c9",
                },
            },
            "fontFamily": {
                "sans": ["Outfit", "-apple-system", "system-ui", "sans-serif"],
                "mono": [
                    "ui-monospace",
                    "SFMono-Regular",
                    "Menlo",
                    "monospace",
                ],
            },
        }

    def get_custom_css(self) -> str:
        return """\
/* ==============================================
   TailAdmin Theme — global overrides
   Design tokens from tailadmin.com
   Outfit font, brand blue, warm gray palette
   ============================================== */

/* Outfit web font */
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

/* Body */
body {
    background-color: var(--canvas) !important;
    color: var(--label-1) !important;
    font-family: 'Outfit', sans-serif !important;
    background-image: none !important;
    transition: background-color 0.2s ease, color 0.2s ease;
}

/* Sidebar: white in light, dark panel in dark mode */
aside > div,
aside .flex.flex-col.h-full {
    background: var(--sidebar-bg) !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
    border-right: 1px solid var(--separator) !important;
}

/* Top header bar */
header.sticky {
    background: var(--header-bg) !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
    border-bottom: 1px solid var(--separator) !important;
    box-shadow: 0 1px 3px 0 rgba(16, 24, 40, 0.06),
                0 1px 2px 0 rgba(16, 24, 40, 0.04);
}

/* Cards: clean with TailAdmin shadow system */
div.rounded-2xl {
    background: var(--card-bg) !important;
    backdrop-filter: none !important;
    -webkit-backdrop-filter: none !important;
    border: 1px solid var(--separator) !important;
    box-shadow: 0 1px 3px 0 rgba(16, 24, 40, 0.06),
                0 1px 2px 0 rgba(16, 24, 40, 0.04);
    transition: background 0.2s ease;
}

/* Card inner headers */
div.rounded-2xl > div.border-b {
    border-color: var(--separator) !important;
}

/* Card text overrides */
div.rounded-2xl h3 {
    color: var(--label-0) !important;
}
div.rounded-2xl p {
    color: var(--label-2);
}

/* Navigation active item — left-bar accent */
.menu-active {
    background: var(--nav-active-bg) !important;
    border-left-color: var(--tint-accent) !important;
    color: var(--tint-accent) !important;
}

/* Navigation hover */
nav a:hover {
    background: var(--nav-hover-bg) !important;
}

/* Sidebar section headers */
nav h3 {
    color: var(--label-3) !important;
    text-transform: uppercase;
    font-size: 0.6875rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}

/* Sidebar nav links */
nav a:not(.menu-active) {
    color: var(--label-2) !important;
}

/* Sidebar borders */
aside .border-b,
aside .border-t {
    border-color: var(--separator) !important;
}

/* Footer */
footer {
    border-color: var(--separator) !important;
}

/* Status dot */
.status-online {
    background-color: var(--dot-on) !important;
    box-shadow: 0 0 6px var(--dot-on-shadow);
}

/* Hide background blobs */
.fixed.inset-0.pointer-events-none {
    opacity: 0 !important;
}

/* Top bar action buttons */
header button.rounded-xl,
header a.rounded-xl {
    background: var(--fill-2) !important;
    color: var(--label-2) !important;
    border: 1px solid var(--separator);
}
header button.rounded-xl:hover,
header a.rounded-xl:hover {
    background: var(--fill-3) !important;
}
header button.rounded-xl i,
header a.rounded-xl i {
    color: var(--label-2) !important;
}

/* Page title */
main h1 {
    color: var(--label-0) !important;
}

/* Gradient border — brand blue */
.gradient-border::before {
    background: linear-gradient(\
135deg, var(--tint-accent), var(--tint-purple), var(--tint-accent)\
) !important;
}

/* Brand text (sidebar) */
aside .text-xl,
aside .text-lg {
    color: var(--label-0) !important;
}

/* Version badge (sidebar) */
aside .font-mono {
    color: var(--label-3) !important;
}

/* User menu in sidebar */
aside .border-t p.text-sm {
    color: var(--label-1) !important;
}
aside .border-t p.text-xs {
    color: var(--label-3) !important;
}

/* Footer text */
footer span, footer div {
    color: var(--label-2) !important;
}
footer .font-semibold {
    color: var(--label-1) !important;
}

/* Scrollbar — TailAdmin style */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: var(--fill-3) !important;
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--fill-4) !important;
}

/* Nordic/accent color overrides in plugin templates */
.text-nordic-600, .dark\\:text-nordic-400,
.text-nordic-500 {
    color: var(--tint-accent) !important;
}
.bg-nordic-500 {
    background-color: var(--tint-accent) !important;
}
.from-nordic-500 {
    --tw-gradient-from: var(--tint-accent) !important;
}

/* Input fields — TailAdmin focus ring */
.input-field {
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    color: var(--label-0);
    border-radius: 8px;
    transition: all 0.15s ease;
}
.input-field::placeholder { color: var(--label-3); }
.input-field:focus {
    outline: none;
    border-color: var(--input-focus-border);
    box-shadow: 0 0 0 4px var(--input-focus-ring);
}

/* Accent button — brand blue */
.btn-primary {
    background: var(--tint-accent);
    border-radius: 8px;
    transition: all 0.15s ease;
}
.btn-primary:hover { background: var(--btn-hover); }
.btn-primary:active { filter: brightness(0.92); }

/* Fade-in animations (TailAdmin subtle) */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(4px); }
    to { opacity: 1; transform: translateY(0); }
}
.fade-up { animation: fadeUp 0.25s ease-out forwards; }
.fade-d1 { animation-delay: 0.03s; opacity: 0; }
.fade-d2 { animation-delay: 0.06s; opacity: 0; }
.fade-d3 { animation-delay: 0.09s; opacity: 0; }
"""

    def get_static_dir(self) -> Path | None:
        static = PLUGIN_DIR / "static"
        return static if static.is_dir() else None

    def get_templates_dir(self) -> Path | None:
        templates = PLUGIN_DIR / "templates"
        return templates if templates.is_dir() else None

    def get_template_overrides(self) -> dict[str, str]:
        return {
            "auth/login.html": "auth/login.html",
            "dashboard.html": "dashboard.html",
        }

    def get_metadata(self) -> dict[str, str]:
        return {
            "display_name": "TailAdmin",
            "description": (
                "TailAdmin design system: brand blue, Outfit font, warm gray palette"
            ),
            "author": "GridBear",
            "preview_image": "preview.png",
            "accent_color": "#465fff",
            "font_imports": [
                "https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap"
            ],
        }
