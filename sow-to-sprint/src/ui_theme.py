from typing import Literal


# ---------------------------------------------------------------------------
# Color tokens (mirrors DESIGN.md)
# ---------------------------------------------------------------------------

SURFACE = "#0e1117"
SURFACE_1 = "#161b22"
SURFACE_2 = "#21262d"
SURFACE_3 = "#282e36"
BORDER = "#30363d"
BORDER_HOVER = "#484f58"
FOCUS = "#388bfd"

PRIMARY = "#10b981"
PRIMARY_HI = "#4edea3"
SUCCESS = "#10b981"
DANGER = "#ef4444"
WARNING = "#f59e0b"
LOW_CONF = "#f97316"

TEXT = "#f0f6fc"
TEXT_2 = "#8b949e"
TEXT_3 = "#6e7681"


# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------

_GLOBAL_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {{
    --surface: {SURFACE};
    --surface-1: {SURFACE_1};
    --surface-2: {SURFACE_2};
    --surface-3: {SURFACE_3};
    --border: {BORDER};
    --border-hover: {BORDER_HOVER};
    --focus: {FOCUS};
    --primary: {PRIMARY};
    --primary-hi: {PRIMARY_HI};
    --success: {SUCCESS};
    --danger: {DANGER};
    --warning: {WARNING};
    --low-conf: {LOW_CONF};
    --text: {TEXT};
    --text-2: {TEXT_2};
    --text-3: {TEXT_3};
}}

html, body, [data-testid="stAppViewContainer"] {{
    background: var(--surface) !important;
    color: var(--text) !important;
    font-family: 'Geist', -apple-system, sans-serif !important;
    font-feature-settings: 'tnum' 1, 'zero' 1;
}}

/* App container tightness */
.block-container {{
    padding-top: 1.25rem !important;
    padding-bottom: 2rem !important;
    max-width: 100% !important;
}}

/* Sidebar */
[data-testid="stSidebar"] {{
    background: #0b1017 !important;
    border-right: 1px solid var(--border) !important;
}}
[data-testid="stSidebar"] * {{
    color: var(--text) !important;
    font-family: 'Geist', sans-serif !important;
}}
/* Hide Streamlit's sidebar collapse button — its Material Icons ligature
   ("keyboard_double_arrow_left") shows as raw text because our font-family
   override clobbers the icon font. Users can still toggle the sidebar via
   the built-in edge handle. */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"] {{
    display: none !important;
}}
[data-testid="stSidebar"] .sidebar-title {{
    font-family: 'JetBrains Mono', monospace;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 11px;
    color: var(--text-2);
    margin-top: 12px;
    margin-bottom: 4px;
}}

/* Headings */
h1, h2, h3, h4 {{
    color: var(--text) !important;
    font-family: 'Geist', sans-serif !important;
    letter-spacing: -0.015em;
}}

/* Metric */
[data-testid="stMetric"] {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 14px;
}}
[data-testid="stMetricLabel"] {{
    font-family: 'JetBrains Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px !important;
    color: var(--text-2) !important;
}}
[data-testid="stMetricValue"] {{
    font-family: 'JetBrains Mono', monospace !important;
    font-weight: 600 !important;
    color: var(--text) !important;
}}
[data-testid="stMetricDelta"] {{
    font-family: 'JetBrains Mono', monospace !important;
}}

/* Buttons */
.stButton > button {{
    background: var(--surface-2);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-family: 'Geist', sans-serif;
    font-weight: 500;
    font-size: 13px;
    padding: 4px 12px;
    transition: none;
}}
.stButton > button:hover {{
    background: var(--surface-3);
    border-color: var(--border-hover);
    color: var(--text);
}}
.stButton > button[kind="primary"] {{
    background: rgba(16, 185, 129, 0.15);
    border: 1px solid var(--primary);
    color: var(--primary);
}}
.stButton > button[kind="primary"]:hover {{
    background: var(--primary);
    color: var(--surface);
}}

/* Text inputs, textareas */
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stSelectbox div[data-baseweb="select"] > div {{
    background: var(--surface) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 4px !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 13px !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus {{
    border-color: var(--focus) !important;
    box-shadow: 0 0 0 1px var(--focus) !important;
}}

/* Multiselect chips */
[data-baseweb="tag"] {{
    background: var(--surface-2) !important;
    border: 1px solid var(--border) !important;
    color: var(--text) !important;
    border-radius: 3px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 10px !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background: transparent;
    gap: 2px;
    border-bottom: 1px solid var(--border);
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: var(--text-2) !important;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    font-family: 'JetBrains Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 11px !important;
    font-weight: 600 !important;
    padding: 10px 14px !important;
}}
.stTabs [aria-selected="true"] {{
    color: var(--primary-hi) !important;
    border-bottom: 2px solid var(--primary-hi) !important;
    background: transparent !important;
}}

/* Dataframe */
[data-testid="stDataFrame"] {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0;
}}
[data-testid="stDataFrame"] * {{
    font-family: 'Geist', sans-serif !important;
    font-size: 12px !important;
}}
[data-testid="stDataFrame"] .col_heading {{
    font-family: 'JetBrains Mono', monospace !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: 10px !important;
    color: var(--text-2) !important;
}}

/* Expander */
.streamlit-expanderHeader, [data-testid="stExpander"] > details > summary {{
    background: var(--surface-1) !important;
    color: var(--text) !important;
    border: 1px solid var(--border) !important;
    border-radius: 4px !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
}}
[data-testid="stExpander"] {{
    background: transparent !important;
}}

/* Toggles / checkboxes */
.stCheckbox label, .stRadio label, .stToggle label {{
    color: var(--text) !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 13px !important;
}}

/* Info / warning / error / success — restyle Streamlit's default alerts */
[data-testid="stAlert"] {{
    border-radius: 4px !important;
    border-left-width: 3px !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 13px !important;
    padding: 12px 14px !important;
}}

/* Bar chart background */
[data-testid="stChart"] {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px;
}}

/* Vertical containers with borders */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background: var(--surface-1);
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    padding: 14px !important;
}}

/* Utility classes we emit from Python */
.ctm-mono {{
    font-family: 'JetBrains Mono', monospace !important;
}}
.ctm-label {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-2);
}}
.ctm-hint {{
    color: var(--text-2);
    font-size: 12px;
}}

/* Badge system */
.ctm-badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    line-height: 14px;
    border: 1px solid transparent;
    margin-right: 4px;
}}
.ctm-badge-approved  {{ background: rgba(16, 185, 129, 0.12); color: {SUCCESS};  border-color: rgba(16, 185, 129, 0.3); }}
.ctm-badge-rejected  {{ background: rgba(239, 68, 68, 0.12);  color: {DANGER};   border-color: rgba(239, 68, 68, 0.3); }}
.ctm-badge-edited    {{ background: rgba(245, 158, 11, 0.12); color: {WARNING};  border-color: rgba(245, 158, 11, 0.3); }}
.ctm-badge-low       {{ background: rgba(249, 115, 22, 0.15); color: {LOW_CONF}; border-color: rgba(249, 115, 22, 0.4); }}
.ctm-badge-generated {{ background: {SURFACE_2}; color: {TEXT_2}; border-color: {BORDER}; }}
.ctm-badge-neutral   {{ background: {SURFACE_2}; color: {TEXT}; border-color: {BORDER}; }}
.ctm-badge-technical  {{ background: rgba(56, 139, 253, 0.15); color: #58a6ff; border-color: rgba(56, 139, 253, 0.3); }}
.ctm-badge-commercial {{ background: rgba(249, 115, 22, 0.15); color: #ff9a5b; border-color: rgba(249, 115, 22, 0.3); }}
.ctm-badge-operations {{ background: rgba(245, 158, 11, 0.15); color: {WARNING}; border-color: rgba(245, 158, 11, 0.3); }}
.ctm-badge-design     {{ background: rgba(78, 222, 163, 0.15); color: {PRIMARY_HI}; border-color: rgba(78, 222, 163, 0.3); }}

.ctm-badge-phase {{ font-size: 10px; padding: 1px 6px; }}

/* Card */
.ctm-card {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px 16px;
    margin-bottom: 8px;
}}
.ctm-card-title {{
    font-family: 'Geist', sans-serif;
    font-size: 15px;
    font-weight: 600;
    color: var(--text);
    letter-spacing: -0.01em;
}}
.ctm-card-subtitle {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-2);
    margin-top: 2px;
    letter-spacing: 0.02em;
}}

/* Alert banner (top of page) */
.ctm-alert {{
    padding: 10px 14px;
    border-radius: 4px;
    font-size: 12px;
    font-family: 'Geist', sans-serif;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 12px;
    border-left: 3px solid;
}}
.ctm-alert-warning {{
    background: rgba(249, 115, 22, 0.10);
    border-left-color: {LOW_CONF};
    color: #ffcaa8;
}}
.ctm-alert-danger {{
    background: rgba(239, 68, 68, 0.10);
    border-left-color: {DANGER};
    color: #ffcccc;
}}
.ctm-alert-success {{
    background: rgba(16, 185, 129, 0.08);
    border-left-color: {SUCCESS};
    color: #b7f0d5;
}}
.ctm-alert-info {{
    background: rgba(56, 139, 253, 0.10);
    border-left-color: {FOCUS};
    color: #cfe1ff;
}}

/* Source clause box (the traceability panel) */
.ctm-source {{
    background: var(--surface);
    border: 1px dashed var(--border);
    border-radius: 4px;
    padding: 12px 14px;
    font-family: 'Geist', sans-serif;
    font-size: 13px;
    color: var(--text);
    line-height: 1.55;
}}
.ctm-source-header {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-2);
    margin-bottom: 6px;
    display: flex;
    justify-content: space-between;
}}
.ctm-source-body em {{
    font-style: normal;
    background: rgba(56, 139, 253, 0.15);
    padding: 0 3px;
    border-radius: 2px;
}}

/* Critical path chain */
.ctm-chain {{ display: flex; flex-direction: column; gap: 6px; }}
.ctm-chain-node {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-left: 3px solid var(--primary);
    padding: 10px 14px;
    border-radius: 4px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}}
.ctm-chain-node.discovery {{ border-left-color: #58a6ff; }}
.ctm-chain-node.build    {{ border-left-color: {PRIMARY_HI}; }}
.ctm-chain-node.uat      {{ border-left-color: {WARNING}; }}
.ctm-chain-node.launch   {{ border-left-color: {LOW_CONF}; }}
.ctm-chain-arrow {{ text-align: center; color: var(--text-3); font-size: 12px; margin: -2px 0; }}

/* Divider */
hr {{ border-color: var(--border) !important; }}
</style>
"""


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def inject_theme() -> str:
    """Return the CSS block. Call with:
        st.markdown(inject_theme(), unsafe_allow_html=True)
    once near the top of every Streamlit page.
    """
    return _GLOBAL_CSS


BadgeKind = Literal[
    "approved", "rejected", "edited", "low", "generated", "neutral",
    "technical", "commercial", "operations", "design",
]


def badge(text: str, kind: BadgeKind = "neutral") -> str:
    """Return an HTML span for a semantic pill badge."""
    return f'<span class="ctm-badge ctm-badge-{kind}">{text}</span>'


def phase_badge(phase: str) -> str:
    """Colour-code a phase name."""
    p = (phase or "").lower()
    if "discovery" in p:
        kind = "technical"
    elif "build" in p:
        kind = "design"
    elif "uat" in p:
        kind = "operations"
    elif "launch" in p:
        kind = "commercial"
    else:
        kind = "neutral"
    return badge(phase, kind)  # type: ignore[arg-type]


def confidence_badge(conf: str) -> str:
    conf = (conf or "").lower()
    if conf == "high":
        return badge("HIGH", "approved")
    if conf == "medium":
        return badge("MED", "edited")
    return badge("LOW", "low")


def status_badge(status: str) -> str:
    s = (status or "generated").lower()
    label = s.upper()
    kind_map = {
        "approved": "approved",
        "rejected": "rejected",
        "edited": "edited",
        "generated": "generated",
    }
    return badge(label, kind_map.get(s, "neutral"))  # type: ignore[arg-type]


def function_badge(function: str) -> str:
    f = (function or "").lower()
    return badge(function.upper(), f if f in {"technical", "commercial", "operations", "design"} else "neutral")  # type: ignore[arg-type]


def mono(text: str) -> str:
    return f'<span class="ctm-mono">{text}</span>'


def label(text: str) -> str:
    return f'<div class="ctm-label">{text}</div>'


def hint(text: str) -> str:
    return f'<span class="ctm-hint">{text}</span>'


AlertKind = Literal["warning", "danger", "success", "info"]


def alert(text: str, kind: AlertKind = "info", icon: str = "•") -> str:
    return (
        f'<div class="ctm-alert ctm-alert-{kind}">'
        f'<span style="font-size: 16px; opacity: 0.9;">{icon}</span>'
        f'<span>{text}</span>'
        f'</div>'
    )


def source_clause(clause_id: str, excerpt: str, extra_header: str = "") -> str:
    return (
        '<div class="ctm-source">'
        f'  <div class="ctm-source-header">'
        f'    <span>SOW SOURCE · {clause_id}</span>'
        f'    <span>{extra_header}</span>'
        f'  </div>'
        f'  <div class="ctm-source-body">{excerpt}</div>'
        f'</div>'
    )
