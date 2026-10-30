"""Corporate presentation layer for Henkia Support Assist.

UI-01.1 is intentionally isolated from Agent Core. The palette and typography
are limited to the values supplied in the Henkia brand manual.
"""
from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
BRAND_DIR = ROOT / "assets" / "brand"
LOGO_POSITIVE = BRAND_DIR / "Imagotipo_Dark_green@2x.png"
ISOTYPE = BRAND_DIR / "Isotipo_principal@2x.png"
AVATAR_64 = BRAND_DIR / "Isotipo_avatar_darkgreen_64.png"
OPTIONAL_SIDEBAR_LOGO = BRAND_DIR / "Imagotipo_sidebar_dark.png"

DARKER = "#00170C"
DARK = "#112F24"
GREEN_MID = "#09B17B"
GREEN_LIGHT = "#00BC52"
SKY = "#B5FDFF"
SKY_MID = "#9DD8FF"
WHITE = "#FFFFFF"


@lru_cache(maxsize=8)
def _bytes(path_text: str) -> bytes:
    return Path(path_text).read_bytes()


@lru_cache(maxsize=8)
def _data_uri(path_text: str) -> str:
    encoded = base64.b64encode(_bytes(path_text)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def asset_uri(path: Path) -> str:
    return _data_uri(str(path.resolve()))


def assistant_avatar():
    """Use Streamlit's default assistant slot; CSS paints the official isotipo.

    Returning ``None`` avoids filesystem URLs and in-memory stream handling differences
    across Streamlit versions. The embedded CSS data URI is self-contained.
    """
    return None


def inject_brand_styles() -> None:
    avatar_uri = asset_uri(AVATAR_64)
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Darker+Grotesque:wght@300&family=Sora:wght@300&display=swap');
        :root {{
          --henkia-darker:{DARKER}; --henkia-dark:{DARK};
          --henkia-green-mid:{GREEN_MID}; --henkia-green-light:{GREEN_LIGHT};
          --henkia-sky:{SKY}; --henkia-sky-mid:{SKY_MID}; --henkia-white:{WHITE};
          --henkia-title-font:'Darker Grotesque'; --henkia-body-font:'Sora';
        }}
        html,body,[class*="css"],[data-testid="stAppViewContainer"],[data-testid="stSidebar"],
        input,textarea,button,label {{font-family:var(--henkia-body-font)!important;font-weight:300!important;color:var(--henkia-dark);}}
        [data-testid="stAppViewContainer"],.stApp {{background:var(--henkia-white);}}
        .block-container {{max-width:1120px;padding-top:1.25rem;padding-bottom:6.5rem;}}
        h1,h2,h3,h4,h5,h6,.henkia-title,.henkia-login-title {{font-family:var(--henkia-title-font)!important;font-weight:300!important;color:var(--henkia-dark)!important;}}
        #MainMenu,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stStatusWidget"],footer {{visibility:hidden;}}

        [data-testid="stSidebar"] {{min-width:260px;max-width:300px;background:var(--henkia-darker);border-right:1px solid var(--henkia-green-mid);}}
        [data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] small,[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {{color:var(--henkia-white)!important;opacity:1!important;}}
        [data-testid="stSidebar"] hr {{border-color:var(--henkia-green-mid)!important;}}
        [data-testid="stSidebar"] [data-testid="stButton"] button,
        [data-testid="stSidebar"] [data-testid="stDownloadButton"] button {{background:var(--henkia-darker)!important;color:var(--henkia-white)!important;border:1px solid var(--henkia-green-mid)!important;border-radius:10px!important;box-shadow:none!important;}}
        [data-testid="stSidebar"] [data-testid="stButton"] button *,
        [data-testid="stSidebar"] [data-testid="stDownloadButton"] button * {{color:var(--henkia-white)!important;opacity:1!important;}}
        [data-testid="stSidebar"] [data-testid="stButton"] button:hover,
        [data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover {{background:var(--henkia-green-mid)!important;color:var(--henkia-darker)!important;}}
        [data-testid="stSidebar"] [data-testid="stButton"] button:hover *,
        [data-testid="stSidebar"] [data-testid="stDownloadButton"] button:hover * {{color:var(--henkia-darker)!important;}}

        /* Debug expander remains dark; UI-01 had white panels with white text. */
        [data-testid="stSidebar"] [data-testid="stExpander"] {{background:var(--henkia-darker)!important;border:1px solid var(--henkia-green-mid)!important;border-radius:10px!important;overflow:hidden;}}
        [data-testid="stSidebar"] [data-testid="stExpander"] details,[data-testid="stSidebar"] [data-testid="stExpander"] summary {{background:var(--henkia-darker)!important;color:var(--henkia-white)!important;}}
        [data-testid="stSidebar"] [data-testid="stExpander"] summary * {{color:var(--henkia-white)!important;opacity:1!important;}}
        [data-testid="stSidebar"] [data-testid="stMetric"] {{background:var(--henkia-darker)!important;border-bottom:1px solid var(--henkia-green-mid);padding:.45rem 0;}}
        [data-testid="stSidebar"] [data-testid="stAlert"] {{background:var(--henkia-sky)!important;color:var(--henkia-dark)!important;border-color:var(--henkia-green-mid)!important;}}
        [data-testid="stSidebar"] [data-testid="stAlert"] * {{color:var(--henkia-dark)!important;}}

        div[data-testid="stButton"] button[kind="primary"],div[data-testid="stFormSubmitButton"] button {{background:var(--henkia-dark)!important;color:var(--henkia-white)!important;border:1px solid var(--henkia-dark)!important;border-radius:10px!important;box-shadow:none!important;}}
        div[data-testid="stFormSubmitButton"] button * {{color:var(--henkia-white)!important;opacity:1!important;}}
        div[data-testid="stButton"] button[kind="primary"]:hover,div[data-testid="stFormSubmitButton"] button:hover {{background:var(--henkia-green-mid)!important;color:var(--henkia-darker)!important;border-color:var(--henkia-green-mid)!important;}}
        div[data-testid="stFormSubmitButton"] button:hover * {{color:var(--henkia-darker)!important;}}

        [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea {{background:var(--henkia-white)!important;color:var(--henkia-dark)!important;border:1px solid var(--henkia-sky-mid)!important;border-radius:10px!important;box-shadow:none!important;}}
        [data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus {{border-color:var(--henkia-green-mid)!important;box-shadow:0 0 0 1px var(--henkia-green-mid)!important;}}
        input::placeholder,textarea::placeholder {{color:var(--henkia-dark)!important;opacity:1!important;}}

        /* One clipping boundary owns the input geometry. */
        [data-testid="stChatInput"] {{background:var(--henkia-white)!important;border:1px solid var(--henkia-green-mid)!important;border-radius:14px!important;box-shadow:none!important;overflow:hidden!important;box-sizing:border-box!important;padding:0!important;}}
        [data-testid="stChatInput"] > div {{border-radius:13px!important;overflow:hidden!important;background:var(--henkia-white)!important;}}
        [data-testid="stChatInput"] textarea {{border:0!important;border-radius:13px 0 0 13px!important;background:var(--henkia-white)!important;box-shadow:none!important;padding-left:1rem!important;}}
        [data-testid="stChatInputSubmitButton"] {{background:var(--henkia-sky)!important;color:var(--henkia-dark)!important;border-radius:9px!important;margin:.34rem!important;}}

        div[data-testid="stChatMessage"] {{background:var(--henkia-white);border:1px solid var(--henkia-sky-mid);border-radius:14px;padding:.35rem .75rem;margin-bottom:.75rem;}}
        div[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{background:var(--henkia-sky);}}
        [data-testid="stChatMessageAvatarUser"] {{background:var(--henkia-dark)!important;color:var(--henkia-white)!important;}}
        [data-testid="stChatMessageAvatarAssistant"] {{
          overflow:hidden!important;
          background-color:var(--henkia-white)!important;
          background-image:url("{avatar_uri}")!important;
          background-position:center!important;
          background-repeat:no-repeat!important;
          background-size:100% 100%!important;
          border:1px solid var(--henkia-green-mid)!important;
          color:transparent!important;
        }}
        [data-testid="stChatMessageAvatarAssistant"] img,
        [data-testid="stChatMessageAvatarAssistant"] svg,
        [data-testid="stChatMessageAvatarAssistant"] span {{display:none!important;visibility:hidden!important;}}
        div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {{max-width:920px;}}
        div[data-testid="stChatMessage"] p {{line-height:1.65;margin:0 0 .78rem 0;color:var(--henkia-dark)!important;}}
        div[data-testid="stChatMessage"] h3 {{font-family:var(--henkia-title-font)!important;font-size:1.45rem;line-height:1.25;margin:1.1rem 0 .5rem;}}
        div[data-testid="stChatMessage"] blockquote {{background:var(--henkia-sky);color:var(--henkia-dark);border-left:4px solid var(--henkia-green-mid);border-radius:0 10px 10px 0;margin:.7rem 0 1rem;padding:.75rem 1rem;}}

        /* Corporate link treatment: remove browser/Streamlit blue without changing semantics. */
        div[data-testid="stChatMessage"] a,
        [data-testid="stMarkdownContainer"] a,
        [data-testid="stDownloadButton"] a {{
          color:var(--henkia-dark)!important;
          text-decoration-color:var(--henkia-green-mid)!important;
          text-decoration-thickness:1px!important;
          text-underline-offset:3px!important;
          overflow-wrap:anywhere!important;
          word-break:break-word!important;
        }}
        div[data-testid="stChatMessage"] a:visited,
        [data-testid="stMarkdownContainer"] a:visited {{color:var(--henkia-dark)!important;}}
        div[data-testid="stChatMessage"] a:hover,
        div[data-testid="stChatMessage"] a:focus-visible,
        [data-testid="stMarkdownContainer"] a:hover,
        [data-testid="stMarkdownContainer"] a:focus-visible {{
          color:var(--henkia-green-mid)!important;
          text-decoration-color:var(--henkia-green-mid)!important;
        }}

        /* Documentary source separator and low-prominence metadata. */
        div[data-testid="stChatMessage"] hr,
        div[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] hr {{
          border:0!important;
          border-top:1px solid var(--henkia-sky-mid)!important;
          margin:1rem 0 .75rem!important;
          opacity:1!important;
        }}
        div[data-testid="stChatMessage"] em {{
          color:var(--henkia-dark)!important;
          opacity:1!important;
        }}
        div[data-testid="stChatMessage"] p,
        div[data-testid="stChatMessage"] li,
        div[data-testid="stChatMessage"] code {{
          overflow-wrap:anywhere;
          word-break:normal;
        }}

        details,[data-testid="stExpander"] {{background:var(--henkia-white)!important;border:1px solid var(--henkia-sky-mid)!important;border-radius:10px!important;}}
        [data-testid="stAlert"] {{background:var(--henkia-sky)!important;color:var(--henkia-dark)!important;border:1px solid var(--henkia-sky-mid)!important;border-left:4px solid var(--henkia-green-mid)!important;border-radius:10px!important;}}

        .henkia-brand-header {{display:flex;align-items:center;gap:1rem;border-bottom:1px solid var(--henkia-sky-mid);padding:.35rem 0 1rem;margin-bottom:1rem;}}
        .henkia-brand-header img {{width:154px;height:auto;display:block;}}
        .henkia-brand-copy {{border-left:1px solid var(--henkia-green-mid);padding-left:1rem;}}
        .henkia-title {{font-size:2.25rem;line-height:1;margin:0;}}
        .henkia-subtitle {{color:var(--henkia-dark)!important;margin:.4rem 0 0;line-height:1.45;opacity:1;}}
        .henkia-status {{display:inline-flex;align-items:center;gap:.45rem;padding:.32rem .7rem;border-radius:999px;color:var(--henkia-darker);background:var(--henkia-sky);border:1px solid var(--henkia-green-mid);font-size:.82rem;}}
        .henkia-status-dot {{width:.45rem;height:.45rem;border-radius:50%;background:var(--henkia-green-light);}}
        .henkia-intro,.henkia-note {{color:var(--henkia-dark)!important;line-height:1.65;opacity:1;}}
        .henkia-intro {{margin-top:1rem;}} .henkia-note {{margin-top:.45rem;}}
        .henkia-welcome {{padding:.2rem 0;color:var(--henkia-dark);}}
        .henkia-version {{color:var(--henkia-white)!important;font-size:.75rem;margin-top:1rem;}}

        .henkia-sidebar-brand {{margin:.2rem 0 1rem;overflow:hidden;}}
        .henkia-sidebar-brand img {{display:block;width:100%;height:auto;}}

        .henkia-login-shell {{max-width:760px;margin:3rem auto 1rem;padding:2rem;background:var(--henkia-white);border:1px solid var(--henkia-sky-mid);border-top:6px solid var(--henkia-green-mid);border-radius:16px;}}
        .henkia-login-logo {{display:block;width:230px;height:auto;margin:0 auto 1.5rem;}}
        .henkia-login-title {{font-size:2.35rem;text-align:center;line-height:1;margin:0;}}
        .henkia-login-copy {{text-align:center;color:var(--henkia-dark)!important;margin:.65rem auto 1rem;max-width:560px;opacity:1;}}
        .henkia-login-note,.henkia-responsible-use {{box-sizing:border-box;width:100%;background:var(--henkia-sky);color:var(--henkia-dark);border-left:4px solid var(--henkia-green-mid);border-radius:0 10px 10px 0;padding:.75rem 1rem;margin:1rem 0 1.25rem;line-height:1.55;}}
        [data-testid="stForm"] {{max-width:760px;margin-left:auto;margin-right:auto;background:var(--henkia-white);border:1px solid var(--henkia-sky-mid);border-radius:16px;padding:1.25rem;}}

        @media(max-width:800px) {{
          .block-container {{padding-top:.75rem;padding-left:1rem;padding-right:1rem;}}
          .henkia-brand-header {{align-items:flex-start;flex-direction:column;gap:.75rem;}}
          .henkia-brand-copy {{border-left:0;border-top:1px solid var(--henkia-green-mid);padding:.75rem 0 0;}}
          .henkia-title {{font-size:1.9rem;}} .henkia-login-shell {{margin-top:1rem;padding:1.25rem;}}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_login_brand() -> None:
    st.markdown(
        f"""
        <div class="henkia-login-shell">
          <img class="henkia-login-logo" src="{asset_uri(LOGO_POSITIVE)}" alt="Henkia">
          <h1 class="henkia-login-title">Henkia Support Assist</h1>
          <p class="henkia-login-copy">Asistente de soporte de impresión, documentación técnica y escalamiento de incidentes.</p>
          <div class="henkia-login-note"><strong>Acceso restringido</strong><br>Validaciones autorizadas para el piloto.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_app_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="henkia-brand-header">
          <img src="{asset_uri(LOGO_POSITIVE)}" alt="Henkia">
          <div class="henkia-brand-copy">
            <h1 class="henkia-title">{title}</h1>
            <p class="henkia-subtitle">{subtitle}</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    # No white container is introduced. Until an approved dark-background logo
    # is supplied, the broken placeholder is deliberately omitted.
    if not OPTIONAL_SIDEBAR_LOGO.exists():
        return
    st.markdown(
        f'<div class="henkia-sidebar-brand"><img src="{asset_uri(OPTIONAL_SIDEBAR_LOGO)}" alt="Henkia"></div>',
        unsafe_allow_html=True,
    )
