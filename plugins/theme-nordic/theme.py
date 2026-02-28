"""Nordic Glass Theme for GridBear Admin UI.

Provides CSS variables, glassmorphism effects, mesh gradients,
and Nordic-inspired styling with teal accent colors.
"""

from pathlib import Path
from typing import Any

from core.interfaces.theme import BaseTheme

PLUGIN_DIR = Path(__file__).resolve().parent


class NordicGlassTheme(BaseTheme):
    name = "theme-nordic"

    def get_css_variables(self) -> dict[str, dict[str, str]]:
        return {
            "light": {
                "--canvas": "#f2f2f7",
                "--elevated": "#ffffff",
                "--sidebar-bg": "rgba(255,255,255,0.82)",
                "--header-bg": "rgba(242,242,247,0.72)",
                "--card-bg": "rgba(255,255,255,0.75)",
                "--separator": "rgba(0,0,0,0.08)",
                "--label-0": "#000000",
                "--label-1": "rgba(0,0,0,0.85)",
                "--label-2": "rgba(0,0,0,0.50)",
                "--label-3": "rgba(0,0,0,0.25)",
                "--fill-1": "rgba(0,0,0,0.03)",
                "--fill-2": "rgba(0,0,0,0.06)",
                "--fill-3": "rgba(0,0,0,0.10)",
                "--fill-4": "rgba(0,0,0,0.14)",
                "--nav-active-bg": "rgba(20,184,166,0.10)",
                "--nav-hover-bg": "rgba(0,0,0,0.04)",
                "--nav-active-icon": "#14b8a6",
                "--tint-accent": "#14b8a6",
                "--tint-green": "#28CD41",
                "--tint-orange": "#FF9500",
                "--tint-red": "#FF3B30",
                "--tint-purple": "#AF52DE",
                "--tint-cyan": "#32ADE6",
                "--input-bg": "rgba(0,0,0,0.04)",
                "--input-border": "rgba(0,0,0,0.10)",
                "--input-focus-border": "#14b8a6",
                "--input-focus-ring": "rgba(20,184,166,0.20)",
                "--btn-hover": "#0d9488",
                "--mesh-1": "rgba(20,184,166,0.06)",
                "--mesh-2": "rgba(175,82,222,0.04)",
                "--mesh-3": "rgba(40,205,65,0.03)",
                "--dot-on": "#28CD41",
                "--dot-on-shadow": "rgba(40,205,65,0.3)",
                "--dot-warn": "#FF9500",
                "--dot-warn-shadow": "rgba(255,149,0,0.3)",
                "--dot-off": "rgba(0,0,0,0.15)",
                "--dot-err": "#FF3B30",
                "--dot-err-shadow": "rgba(255,59,48,0.3)",
                "--overlay-bg": "rgba(0,0,0,0.25)",
                "--table-hover": "rgba(0,0,0,0.02)",
                "--pill-green-bg": "rgba(40,205,65,0.10)",
                "--pill-orange-bg": "rgba(255,149,0,0.10)",
                "--icon-accent-bg": "rgba(20,184,166,0.10)",
                "--icon-green-bg": "rgba(40,205,65,0.10)",
                "--icon-orange-bg": "rgba(255,149,0,0.10)",
                "--icon-purple-bg": "rgba(175,82,222,0.10)",
                "--icon-cyan-bg": "rgba(50,173,230,0.10)",
                "--avatar-from": "#14b8a6",
                "--avatar-to": "#AF52DE",
                "--version-color": "rgba(0,0,0,0.20)",
                "--shield-color": "rgba(20,184,166,0.35)",
            },
            "dark": {
                "--canvas": "#1c1c1e",
                "--elevated": "#2c2c2e",
                "--sidebar-bg": "rgba(28,28,30,0.85)",
                "--header-bg": "rgba(44,44,46,0.72)",
                "--card-bg": "rgba(44,44,46,0.60)",
                "--separator": "rgba(255,255,255,0.08)",
                "--label-0": "#ffffff",
                "--label-1": "rgba(255,255,255,0.85)",
                "--label-2": "rgba(255,255,255,0.55)",
                "--label-3": "rgba(255,255,255,0.25)",
                "--fill-1": "rgba(255,255,255,0.04)",
                "--fill-2": "rgba(255,255,255,0.07)",
                "--fill-3": "rgba(255,255,255,0.12)",
                "--fill-4": "rgba(255,255,255,0.16)",
                "--nav-active-bg": "rgba(45,212,191,0.18)",
                "--nav-hover-bg": "rgba(255,255,255,0.06)",
                "--nav-active-icon": "#2dd4bf",
                "--tint-accent": "#2dd4bf",
                "--tint-green": "#30D158",
                "--tint-orange": "#FF9F0A",
                "--tint-red": "#FF453A",
                "--tint-purple": "#BF5AF2",
                "--tint-cyan": "#64D2FF",
                "--input-bg": "rgba(255,255,255,0.06)",
                "--input-border": "rgba(255,255,255,0.08)",
                "--input-focus-border": "#2dd4bf",
                "--input-focus-ring": "rgba(45,212,191,0.25)",
                "--btn-hover": "#14b8a6",
                "--mesh-1": "rgba(45,212,191,0.12)",
                "--mesh-2": "rgba(191,90,242,0.08)",
                "--mesh-3": "rgba(48,209,88,0.04)",
                "--dot-on": "#30D158",
                "--dot-on-shadow": "rgba(48,209,88,0.4)",
                "--dot-warn": "#FF9F0A",
                "--dot-warn-shadow": "rgba(255,159,10,0.3)",
                "--dot-off": "rgba(255,255,255,0.20)",
                "--dot-err": "#FF453A",
                "--dot-err-shadow": "rgba(255,69,58,0.3)",
                "--overlay-bg": "rgba(0,0,0,0.50)",
                "--table-hover": "rgba(255,255,255,0.03)",
                "--pill-green-bg": "rgba(48,209,88,0.15)",
                "--pill-orange-bg": "rgba(255,159,10,0.15)",
                "--icon-accent-bg": "rgba(45,212,191,0.15)",
                "--icon-green-bg": "rgba(48,209,88,0.15)",
                "--icon-orange-bg": "rgba(255,159,10,0.15)",
                "--icon-purple-bg": "rgba(191,90,242,0.15)",
                "--icon-cyan-bg": "rgba(100,210,255,0.15)",
                "--avatar-from": "#2dd4bf",
                "--avatar-to": "#BF5AF2",
                "--version-color": "rgba(255,255,255,0.15)",
                "--shield-color": "rgba(45,212,191,0.35)",
            },
        }

    def get_tailwind_config(self) -> dict[str, Any]:
        return {
            "borderRadius": {
                "ios": "12px",
                "ios-lg": "16px",
                "ios-xl": "20px",
            },
        }

    def get_custom_css(self) -> str:
        return """\
/* ==============================================
   Nordic Glass Theme — global overrides
   Uses !important to override Tailwind CDN utilities
   ============================================== */

/* Body: override bg-void-100 / dark:bg-void-950 */
body {
    background-color: var(--canvas) !important;
    color: var(--label-1) !important;
    background-image:
        radial-gradient(ellipse at 20% 0%, var(--mesh-1) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 100%, var(--mesh-2) 0%, transparent 50%),
        radial-gradient(ellipse at 50% 50%, var(--mesh-3) 0%, transparent 70%) !important;
    transition: background-color 0.4s ease, color 0.3s ease;
}

/* Sidebar glass */
aside > div,
aside .flex.flex-col.h-full {
    background: var(--sidebar-bg) !important;
    backdrop-filter: blur(50px) saturate(200%) !important;
    -webkit-backdrop-filter: blur(50px) saturate(200%) !important;
    border-color: var(--separator) !important;
}

/* Top header bar glass */
header.sticky {
    background: var(--header-bg) !important;
    backdrop-filter: blur(40px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(40px) saturate(180%) !important;
    border-color: var(--separator) !important;
}

/* Cards */
div.rounded-2xl {
    background: var(--card-bg) !important;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border-color: var(--separator) !important;
    transition: background 0.4s ease;
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

/* Navigation active item */
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
}

/* Sidebar nav links default color */
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

/* Background blobs — softer with theme mesh colors */
.fixed.inset-0.pointer-events-none {
    opacity: 0 !important;
}

/* Top bar action buttons */
header button.rounded-xl,
header a.rounded-xl {
    background: var(--fill-2) !important;
    color: var(--label-2) !important;
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

/* Gradient border effect — use accent variable */
.gradient-border::before {
    background: linear-gradient(135deg, var(--tint-accent), var(--tint-cyan, #32ADE6), var(--tint-accent)) !important;
}

/* Brand text */
aside .text-xl,
aside .text-lg {
    color: var(--label-0) !important;
}

/* Version badge */
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

/* Scrollbar */
::-webkit-scrollbar-thumb {
    background: var(--fill-3) !important;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--fill-4) !important;
}

/* Nordic/accent color overrides in text and backgrounds */
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

/* Glass-style input fields (for override templates) */
.input-field {
    background: var(--input-bg);
    border: 1px solid var(--input-border);
    color: var(--label-0);
    transition: all 0.2s ease;
}
.input-field::placeholder { color: var(--label-3); }
.input-field:focus {
    outline: none;
    border-color: var(--input-focus-border);
    box-shadow: 0 0 0 3px var(--input-focus-ring);
}

/* Accent button */
.btn-primary {
    background: var(--tint-accent);
    transition: all 0.2s ease;
}
.btn-primary:hover { background: var(--btn-hover); }
.btn-primary:active { filter: brightness(0.92); }

/* Fade-in animations */
@keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
.fade-up { animation: fadeUp 0.5s cubic-bezier(0.25, 0.1, 0.25, 1) forwards; }
.fade-d1 { animation-delay: 0.05s; opacity: 0; }
.fade-d2 { animation-delay: 0.15s; opacity: 0; }
.fade-d3 { animation-delay: 0.25s; opacity: 0; }
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
            "display_name": "Nordic Glass",
            "description": "Glassmorphism with teal accent, mesh gradients, and Nordic-inspired styling",
            "author": "GridBear",
            "preview_image": "preview.png",
            "accent_color": "#14b8a6",
        }
