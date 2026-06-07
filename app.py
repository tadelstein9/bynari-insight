"""
Bynari Insight — Streamlit web app
Independent structural reference data for eBay sellers.

All data access (cassini.db categories, eBay Browse API) is mediated
through api.tadelstein.com. The Streamlit app itself ships no data
and holds no credentials.
"""

import base64
import io
import json
import re
import tempfile
from pathlib import Path
from urllib.parse import quote_plus, urlparse, parse_qs

import requests
import streamlit as st

from lqr_analyzer import parse_lqr


# --------------------------------------------------------------------
# Page config and styling
# --------------------------------------------------------------------

st.set_page_config(
    page_title="Bynari Insight",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .stApp, .stApp p, .stApp li, .stApp label, .stApp h1,
      .stApp h2, .stApp h3, .stApp h4 {
        font-family: Georgia, "Times New Roman", serif;
      }
      h1, h2, h3 {
        font-weight: 700;
        letter-spacing: -0.01em;
      }
      .stTabs [data-baseweb="tab-list"] button {
        font-family: Georgia, serif;
        font-size: 1.05rem;
      }
      .small-note {
        color: #666;
        font-size: 0.9rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------
# Bynari API (api.tadelstein.com)
# --------------------------------------------------------------------

BYNARI_API_BASE = "https://api.tadelstein.com"
BYNARI_ITEM_URL = f"{BYNARI_API_BASE}/item.php"
BYNARI_CATEGORY_URL = f"{BYNARI_API_BASE}/category.php"

# User-Agent so HostGator's mod_security doesn't reject us as a bot.
BYNARI_UA = {"User-Agent": "Mozilla/5.0 (Bynari Insight Streamlit)"}


def _api_get(url: str, params: dict, timeout: int = 15):
    """Make a GET request to the Bynari API. Returns (data, error_str)."""
    try:
        r = requests.get(url, params=params, headers=BYNARI_UA, timeout=timeout)
    except requests.exceptions.Timeout:
        return None, "Request timed out. Try again in a moment."
    except requests.exceptions.RequestException as e:
        return None, f"Network error: {e}"

    if r.status_code >= 500:
        return None, f"API error (HTTP {r.status_code})."

    try:
        return r.json(), None
    except ValueError:
        snippet = (r.text or "")[:200]
        return None, f"Couldn't parse API response. First 200 chars: {snippet}"


# --------------------------------------------------------------------
# Category lookups (via api.tadelstein.com/category.php)
# --------------------------------------------------------------------

@st.cache_data(ttl=3600)
def category_lookup_by_id(category_id: str):
    """Returns dict or None."""
    data, err = _api_get(
        BYNARI_CATEGORY_URL,
        {"op": "by_id", "id": str(category_id)},
    )
    if err or data is None:
        return None
    return data if isinstance(data, dict) else None


@st.cache_data(ttl=3600)
def category_lookup_by_name(name: str, limit: int = 5):
    """Returns list of dicts. Empty list if nothing matches."""
    if not name:
        return []
    data, err = _api_get(
        BYNARI_CATEGORY_URL,
        {"op": "by_name", "q": name.strip(), "limit": limit},
    )
    if err or data is None:
        return []
    return data if isinstance(data, list) else []


@st.cache_data(ttl=3600)
def item_specifics_for_category(category_id: str):
    """Returns list of dicts: aspect_name, required, allowed_values, etc."""
    data, err = _api_get(
        BYNARI_CATEGORY_URL,
        {"op": "specifics", "id": str(category_id)},
    )
    if err or data is None:
        return []
    return data if isinstance(data, list) else []


# --------------------------------------------------------------------
# eBay URL helpers
# --------------------------------------------------------------------

def build_ebay_search_url(query: str, sold: bool = False) -> str:
    base = "https://www.ebay.com/sch/i.html?_nkw=" + quote_plus(query.strip())
    if sold:
        base += "&LH_Sold=1&LH_Complete=1&_ipg=50&_sop=12"
    return base


def extract_category_id(text: str):
    if not text:
        return None
    text = text.strip()
    if text.isdigit():
        return text
    try:
        parsed = urlparse(text)
        if parsed.netloc and "ebay" in parsed.netloc:
            qs = parse_qs(parsed.query)
            if "_sacat" in qs and qs["_sacat"][0].isdigit():
                return qs["_sacat"][0]
            m = re.search(r"/b/[^/]+/(\d+)", parsed.path)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


# --------------------------------------------------------------------
# Listing fetch (via api.tadelstein.com/item.php — Browse API)
# --------------------------------------------------------------------

def fetch_listing(item_id: str):
    """Returns (data_dict, error_string)."""
    try:
        r = requests.get(
            BYNARI_ITEM_URL,
            params={"item": item_id},
            headers=BYNARI_UA,
            timeout=15,
        )
    except requests.exceptions.Timeout:
        return None, "Request timed out. Try again in a moment."
    except requests.exceptions.RequestException as e:
        return None, f"Network error: {e}"

    if r.status_code == 400:
        return None, "That doesn't look like a valid item number."
    if r.status_code == 404:
        return None, "Item not found on eBay."
    if r.status_code >= 500:
        return None, f"eBay or our API had a problem (HTTP {r.status_code})."

    try:
        return r.json(), None
    except ValueError:
        snippet = (r.text or "")[:300].replace("\n", " ")
        return None, (
            f"Couldn't parse the response (HTTP {r.status_code}, "
            f"{len(r.text or '')} bytes). First 300 chars: {snippet}"
        )


def translate_browse_response(api_data: dict) -> dict:
    """Translate Browse API response into the shape rendering code expects."""
    specs = {}
    for aspect in api_data.get("localizedAspects") or []:
        name = aspect.get("name", "").strip()
        value = aspect.get("value", "").strip()
        if name and value:
            specs[name] = value

    cat_id = ""
    cat_path = api_data.get("categoryIdPath", "")
    if cat_path:
        cat_id = cat_path.split("|")[-1]

    raw_item_id = api_data.get("itemId", "")
    item_id_clean = ""
    if "|" in raw_item_id:
        parts = raw_item_id.split("|")
        if len(parts) >= 2:
            item_id_clean = parts[1]
    else:
        item_id_clean = raw_item_id

    price_block = api_data.get("price") or {}

    return {
        "title": api_data.get("title", ""),
        "specs": specs,
        "catId": cat_id,
        "itemId": item_id_clean,
        "url": api_data.get("itemWebUrl", ""),
        "condition": api_data.get("condition", ""),
        "price": price_block.get("value", ""),
        "currency": price_block.get("currency", ""),
    }


# --------------------------------------------------------------------
# Datasheet generation
# --------------------------------------------------------------------

def render_specific(s: dict, indent: str = "    ") -> list:
    lines = [f"{indent}• {s['aspect_name']}"]
    if s["allowed_values"]:
        vals = s["allowed_values"]
        if len(vals) <= 12:
            lines.append(f"{indent}    Allowed values: {', '.join(vals)}")
        else:
            preview = ", ".join(vals[:12])
            lines.append(
                f"{indent}    Allowed values ({len(vals)} total): "
                f"{preview}, ..."
            )
    else:
        lines.append(f"{indent}    Allowed values: not enumerated — "
                     "consult an LLM")
    return lines


def build_single_category_datasheet(cat: dict, query: str = "") -> str:
    specifics = item_specifics_for_category(cat["category_id"])
    required = [s for s in specifics if s["required"]]
    recommended = [s for s in specifics if not s["required"]]

    out = []
    out.append("BYNARI INSIGHT — CATEGORY DATASHEET")
    out.append("=" * 60)
    out.append("")
    if query:
        out.append(f"Your search:  {query}")
    out.append(f"Category:     {cat['full_path'] or cat['category_name']}")
    out.append(f"Category ID:  {cat['category_id']}")
    out.append("")
    out.append("-" * 60)
    out.append(f"REQUIRED ITEM SPECIFICS ({len(required)})")
    out.append("-" * 60)
    if not required:
        out.append("  (Bynari has no required fields recorded for this "
                   "category — consult an LLM.)")
    else:
        for s in required:
            out.extend(render_specific(s, indent="  "))
    out.append("")
    out.append("-" * 60)
    out.append(f"RECOMMENDED ITEM SPECIFICS ({len(recommended)})")
    out.append("-" * 60)
    if not recommended:
        out.append("  (Bynari has no recommended fields recorded for this "
                   "category — consult an LLM.)")
    else:
        for s in recommended:
            out.extend(render_specific(s, indent="  "))
    out.append("")
    out.append("=" * 60)
    out.append("Hand this datasheet to your own LLM along with details")
    out.append("about your item to generate a complete listing draft.")
    return "\n".join(out)


def build_multi_category_datasheet(category_pairs: list) -> str:
    out = []
    out.append("BYNARI INSIGHT — CATEGORY DATASHEETS")
    out.append("=" * 60)
    out.append("")
    out.append("Your Listing Quality Report has findings in these")
    out.append("categories. Below is the structural data Bynari has")
    out.append("for each one.")
    out.append("")

    for lqr_name, condition, cat in category_pairs:
        out.append("=" * 60)
        if cat is None:
            out.append(f"{lqr_name} ({condition})")
            out.append("=" * 60)
            out.append("")
            out.append("  Bynari does not have data for this category by")
            out.append("  name. Use Tab 1 (Category Datasheet) to look it")
            out.append("  up by eBay URL or category ID.")
            out.append("")
            continue

        out.append(f"{lqr_name} ({condition})")
        out.append(f"  Cassini path: {cat['full_path'] or cat['category_name']}")
        out.append(f"  Category ID:  {cat['category_id']}")
        out.append("=" * 60)
        out.append("")

        specifics = item_specifics_for_category(cat["category_id"])
        required = [s for s in specifics if s["required"]]
        recommended = [s for s in specifics if not s["required"]]

        out.append(f"REQUIRED ITEM SPECIFICS ({len(required)})")
        out.append("-" * 40)
        if not required:
            out.append("  (none recorded — consult an LLM)")
        else:
            for s in required:
                out.extend(render_specific(s, indent="  "))
        out.append("")

        out.append(f"RECOMMENDED ITEM SPECIFICS ({len(recommended)})")
        out.append("-" * 40)
        if not recommended:
            out.append("  (none recorded — consult an LLM)")
        else:
            for s in recommended:
                out.extend(render_specific(s, indent="  "))
        out.append("")

    out.append("=" * 60)
    out.append("Hand this datasheet to your own LLM along with details")
    out.append("about each item to generate listing drafts.")
    return "\n".join(out)


# --------------------------------------------------------------------
# Header
# --------------------------------------------------------------------

st.title("Bynari Insight")
st.markdown(
    '<div class="small-note">'
    "Independent structural reference data for eBay sellers."
    "</div>",
    unsafe_allow_html=True,
)
st.write("")


# --------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------

tab1, tab2, tab3 = st.tabs([
    "Category Datasheet",
    "Multi-Category Datasheet",
    "Analyze a Listing",
])


# ========================  TAB 1  ===================================
with tab1:
    st.header("Category Finder")
    st.write(
        "Describe what you're selling in plain English. Bynari finds the "
        "right eBay category, then gives you the structural data you need "
        "to list it — what's required, what's recommended, what allowed "
        "values eBay accepts."
    )

    BROKER_BASE_TAB1 = "https://api.tadelstein.com"
    BROKER_TIMEOUT_TAB1 = 10
    BROKER_HEADERS_TAB1 = {
        "Accept": "application/json",
        "User-Agent": "Bynari-Insight/0.1",
    }

    DIRECTIVE_TAB1 = (
        "eBay will expect you to fill in these items when you create "
        "your listing. If you skip the required fields, eBay will "
        "publish your listing but it won't rank in search — buyers "
        "won't see it. The recommended fields aren't strictly required, "
        "but listings that include them appear in far more buyer filter "
        "searches. Use the allowed values exactly as shown where they're "
        "listed; eBay matches those terms against buyer filters."
    )

    REQUIRED_NOTE_TAB1 = (
        "Fill in every field below. Listings without these are not "
        "ranked in search results."
    )

    RECOMMENDED_NOTE_TAB1 = (
        "Fill in as many as apply. Each one is a buyer filter your "
        "listing appears in."
    )

    def _tab1_breadcrumb(category_name, ancestors):
        path = [a["categoryName"] for a in reversed(ancestors)]
        path.append(category_name)
        return " > ".join(path)

    def _tab1_render_aspect(aspect):
        name = aspect.get("name", "(unnamed)")
        mode = aspect.get("mode", "")
        allowed = aspect.get("allowedValues", []) or []
        count = aspect.get("allowedValueCount", len(allowed))
        label = f"• **{name}**"
        if mode == "SELECTION_ONLY":
            label += " — selection only"
        elif mode == "FREE_TEXT":
            label += " — free text"
        st.markdown(label)
        if count > 0:
            preview = ", ".join(allowed[:8])
            if count > 8:
                preview += f", … ({count} total)"
            st.caption(f"Allowed values: {preview}")

    def _tab1_build_pdf(category, aspects):
        from io import BytesIO
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import SimpleDocTemplate, Paragraph

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=0.75 * inch, rightMargin=0.75 * inch,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            title=f"Bynari Insight — {category['name']}",
            author="Bynari Insight",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle("t", parent=styles["Title"], fontSize=18, spaceAfter=6)
        sub = ParagraphStyle("s", parent=styles["Normal"], fontSize=10, textColor="#555555", spaceAfter=12)
        d = ParagraphStyle("d", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=14)
        h = ParagraphStyle("h", parent=styles["Heading2"], fontSize=13, spaceBefore=12, spaceAfter=4)
        n = ParagraphStyle("n", parent=styles["BodyText"], fontSize=9, textColor="#555555", spaceAfter=10)
        a_s = ParagraphStyle("a", parent=styles["BodyText"], fontSize=10, leftIndent=12, spaceAfter=2)
        v = ParagraphStyle("v", parent=styles["BodyText"], fontSize=9, textColor="#444444", leftIndent=24, spaceAfter=6)

        story = [
            Paragraph(f"Datasheet — {category['name']}", title_style),
            Paragraph(f"{category['breadcrumb']} &nbsp;·&nbsp; Category ID {category['id']}", sub),
            Paragraph(DIRECTIVE_TAB1, d),
        ]

        req = [x for x in aspects if x.get("required")]
        rec = [x for x in aspects if not x.get("required")]

        story.append(Paragraph(f"Required item specifics ({len(req)})", h))
        story.append(Paragraph(REQUIRED_NOTE_TAB1, n))
        if req:
            for x in req:
                _tab1_pdf_aspect(story, x, a_s, v)
        else:
            story.append(Paragraph("None recorded.", n))

        story.append(Paragraph(f"Recommended item specifics ({len(rec)})", h))
        story.append(Paragraph(RECOMMENDED_NOTE_TAB1, n))
        if rec:
            for x in rec:
                _tab1_pdf_aspect(story, x, a_s, v)
        else:
            story.append(Paragraph("None recorded.", n))

        doc.build(story)
        return buf.getvalue()

    def _tab1_pdf_aspect(story, aspect, aspect_style, values_style):
        from reportlab.platypus import Paragraph
        name = aspect.get("name", "(unnamed)")
        mode = aspect.get("mode", "")
        allowed = aspect.get("allowedValues", []) or []
        count = aspect.get("allowedValueCount", len(allowed))
        label = f"<b>{name}</b>"
        if mode == "SELECTION_ONLY":
            label += " — selection only"
        elif mode == "FREE_TEXT":
            label += " — free text"
        story.append(Paragraph(label, aspect_style))
        if count > 0:
            preview = ", ".join(allowed[:8])
            if count > 8:
                preview += f", … ({count} total)"
            story.append(Paragraph(f"Allowed values: {preview}", values_style))

    if "tab1_last_query" not in st.session_state:
        st.session_state.tab1_last_query = None
    if "tab1_selected" not in st.session_state:
        st.session_state.tab1_selected = None
    if "tab1_suggestions" not in st.session_state:
        st.session_state.tab1_suggestions = None

    tab1_query = st.text_input(
        "What are you selling?",
        key="tab1_query_input",
        help="A short description. Examples: '8 GB RAM', "
             "'mens leather jacket', 'vintage pocket watch'",
    )

    if st.button("Find category", type="primary", key="tab1_find_btn"):
        st.session_state.tab1_selected = None
        st.session_state.tab1_suggestions = None
        st.session_state.tab1_last_query = tab1_query
        try:
            r = requests.get(
                f"{BROKER_BASE_TAB1}/category_suggestions.php",
                params={"q": tab1_query},
                headers=BROKER_HEADERS_TAB1,
                timeout=BROKER_TIMEOUT_TAB1,
            )
            r.raise_for_status()
            st.session_state.tab1_suggestions = r.json()
        except requests.RequestException as e:
            st.error(f"Could not reach the category service: {e}")

    if st.session_state.tab1_suggestions:
        st.divider()
        st.subheader(f"Categories for: {st.session_state.tab1_last_query}")
        st.caption(
            "eBay ranks these by how likely each category fits your "
            "item. Pick the one that matches what you have."
        )
        cats = st.session_state.tab1_suggestions.get("categorySuggestions", [])
        if not cats:
            st.info("No category suggestions returned for that query.")
        for i, sug in enumerate(cats):
            c = sug["category"]
            ancestors = sug.get("categoryTreeNodeAncestors", [])
            breadcrumb = _tab1_breadcrumb(c["categoryName"], ancestors)
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{c['categoryName']}**")
                st.caption(f"{breadcrumb} · Category ID `{c['categoryId']}`")
            with col2:
                if st.button("Use this", key=f"tab1_pick_{i}"):
                    st.session_state.tab1_selected = {
                        "id": c["categoryId"],
                        "name": c["categoryName"],
                        "breadcrumb": breadcrumb,
                    }
                    st.success("Got it — your datasheet is below ↓")

    if st.session_state.tab1_selected:
        sel = st.session_state.tab1_selected
        st.divider()
        st.subheader(f"Datasheet — {sel['name']}")
        st.caption(f"{sel['breadcrumb']} · Category ID `{sel['id']}`")
        try:
            r = requests.get(
                f"{BROKER_BASE_TAB1}/item_aspects.php",
                params={"category_id": sel["id"]},
                headers=BROKER_HEADERS_TAB1,
                timeout=BROKER_TIMEOUT_TAB1,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            st.error(f"Could not load the datasheet: {e}")
            data = None

        if data is not None:
            aspects = data.get("aspects", [])
            if not aspects:
                st.info("No item specifics are recorded for this category.")
            else:
                st.info(DIRECTIVE_TAB1)
                req = [x for x in aspects if x.get("required")]
                rec = [x for x in aspects if not x.get("required")]

                st.markdown(f"### Required item specifics ({len(req)})")
                st.caption(REQUIRED_NOTE_TAB1)
                if req:
                    for x in req:
                        _tab1_render_aspect(x)
                else:
                    st.caption("None recorded.")

                st.markdown(f"### Recommended item specifics ({len(rec)})")
                st.caption(RECOMMENDED_NOTE_TAB1)
                if rec:
                    for x in rec:
                        _tab1_render_aspect(x)
                else:
                    st.caption("None recorded.")

                st.divider()
                pdf_bytes = _tab1_build_pdf(sel, aspects)
                st.download_button(
                    label="Save this list as PDF",
                    data=pdf_bytes,
                    file_name="bynari-datasheet.pdf",
                    mime="application/pdf",
                    type="primary",
                    key="tab1_pdf_dl",
                )
# ========================  TAB 2  ===================================
with tab2:

    st.header("Multi-category datasheet from your LQR")
    st.write(
        "eBay produces a **Listing Quality Report** for every active "
        "seller. It flags which categories of yours need work. Bynari "
        "reads the report only to learn which categories to produce "
        "datasheets for — it does not reproduce eBay's analysis."
    )

    st.markdown(
        "**Don't have your LQR yet?** It's in eBay **Seller Hub → "
        "Performance → Listing Quality Report → Download**. The file "
        "is an XLSX you save to your computer."
    )

    uploaded = st.file_uploader(
        "Upload your LQR XLSX when you have it",
        type=["xlsx"],
        key="t2_upload",
    )

    st.markdown(
        '<div class="small-note">Nothing about the file is kept after '
        "this session ends.</div>",
        unsafe_allow_html=True,
    )

    if uploaded is not None:
        with tempfile.NamedTemporaryFile(
            suffix=".xlsx", delete=False
        ) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        try:
            report = parse_lqr(tmp_path)
        except Exception as e:
            st.error(
                f"Could not parse the LQR file: {e}\n\n"
                "eBay may have changed the LQR format. Please open "
                "the file in Excel to confirm it's the standard LQR."
            )
        else:
            categories_with_findings = {}
            for l in report.listings:
                if l.severity != "NONE":
                    key = (l.category, l.condition)
                    categories_with_findings[key] = (
                        categories_with_findings.get(key, 0) + 1
                    )

            st.markdown("---")

            if not categories_with_findings:
                st.success(
                    "Your LQR shows no listings need attention. "
                    "All clean. Nothing to datasheet."
                )
            else:
                st.markdown(
                    f"**Your LQR flags {len(categories_with_findings)} "
                    f"categor"
                    f"{'y' if len(categories_with_findings) == 1 else 'ies'} "
                    f"with work to do.**"
                )

                category_pairs = []
                for (cat_name, condition), count in sorted(
                    categories_with_findings.items()
                ):
                    matches = category_lookup_by_name(cat_name)
                    if matches:
                        category_pairs.append(
                            (cat_name, condition, matches[0])
                        )
                    else:
                        category_pairs.append(
                            (cat_name, condition, None)
                        )

                for cat_name, condition, cat in category_pairs:
                    if cat is None:
                        st.markdown(
                            f"- **{cat_name}** ({condition}) — "
                            "_no Bynari data_"
                        )
                    else:
                        st.markdown(
                            f"- **{cat_name}** ({condition}) → "
                            f"Cassini ID `{cat['category_id']}`"
                        )

                st.markdown("")
                st.markdown(
                    "**↓ Your consolidated datasheet is below.** "
                    "_It takes a moment to build._"
                )

                with st.spinner("Building your datasheet..."):
                    doc = build_multi_category_datasheet(category_pairs)
                st.markdown("---")
                st.text_area(
                    "Consolidated datasheet — copy this and hand it "
                    "to your LLM",
                    value=doc,
                    height=600,
                    key="t2_output",
                )


# ========================  TAB 3  ===================================

with tab3:
    st.header("Analyze a Listing")
    st.write(
        "Paste an eBay item number below. Bynari fetches the listing's "
        "public data and compares it against the structural data we have "
        "for that category — what's required, what's recommended, what's "
        "missing."
    )

    item_input = st.text_input(
        "eBay item number",
        placeholder="e.g., 206276547370",
        key="t3_item",
    )

    if st.button("Analyze", type="primary", key="t3_analyze"):
        item_id = item_input.strip()
        if not item_id.isdigit() or not (9 <= len(item_id) <= 15):
            st.error(
                "That doesn't look like an eBay item number. eBay item "
                "numbers are 9 to 15 digits."
            )
        else:
            with st.spinner("Fetching listing data..."):
                api_data, error = fetch_listing(item_id)

            if error:
                st.error(error)
            else:
                data = translate_browse_response(api_data)

                cat = None
                cat_id = data.get("catId", "")
                if cat_id:
                    cat = category_lookup_by_id(cat_id)

                st.success("Listing fetched.")
                st.markdown(f"**Title:** {data['title'] or '_(not found)_'}")
                if data["itemId"]:
                    st.markdown(f"**Item ID:** `{data['itemId']}`")
                if data["price"]:
                    st.markdown(
                        f"**Price:** {data['price']} {data['currency']}"
                    )
                if data["condition"]:
                    st.markdown(f"**Condition:** {data['condition']}")
                if cat:
                    st.markdown(
                        f"**Category:** "
                        f"{cat['full_path'] or cat['category_name']} "
                        f"(`{cat['category_id']}`)"
                    )
                elif cat_id:
                    st.markdown(
                        f"**Category ID:** `{cat_id}` "
                        "_(not in Bynari's data — analysis below uses "
                        "listing data only)_"
                    )
                else:
                    st.warning(
                        "eBay didn't return a category ID for this "
                        "listing. Comparison against Bynari's data is "
                        "not possible without it."
                    )

                st.markdown("---")

                st.markdown("### Title")
                title = data["title"]
                title_len = len(title)
                condition_words = [
                    "new without tags", "new with tags", "serviced",
                    "restored", "excellent condition", "mint", "like new",
                    "nwt", "nib", "nos", "refurbished",
                    "seller refurbished", "pre-owned", "remanufactured",
                    "new (other)",
                ]
                has_condition = any(
                    w in title.lower() for w in condition_words
                )
                st.markdown(
                    f"- Length: **{title_len} characters** "
                    "(eBay's title limit is 80)"
                )
                st.markdown(
                    f"- Condition signal in title: "
                    f"**{'present' if has_condition else 'not detected'}**"
                )

                specs = data["specs"]
                st.markdown("---")
                st.markdown(
                    f"### Item specifics on this listing ({len(specs)})"
                )
                if not specs:
                    st.markdown(
                        "_eBay didn't return any item specifics for "
                        "this listing._"
                    )
                else:
                    import pandas as pd
                    spec_rows = [
                        {"Field": k, "Value": v}
                        for k, v in sorted(specs.items())
                    ]
                    st.dataframe(
                        pd.DataFrame(spec_rows),
                        use_container_width=True,
                        hide_index=True,
                    )

                if cat is not None:
                    cassini_specifics = item_specifics_for_category(
                        cat["category_id"]
                    )
                    listed_field_names = {
                        k.lower(): k for k in specs.keys()
                    }
                    required = [
                        s for s in cassini_specifics if s["required"]
                    ]
                    recommended = [
                        s for s in cassini_specifics if not s["required"]
                    ]

                    st.markdown("---")
                    st.markdown(
                        f"### Required for this category ({len(required)})"
                    )
                    if not required:
                        st.markdown("_None recorded._")
                    else:
                        import pandas as pd
                        req_rows = []
                        for s in required:
                            present = (
                                s["aspect_name"].lower()
                                in listed_field_names
                            )
                            req_rows.append({
                                "Field": s["aspect_name"],
                                "Present on listing": "✔" if present else "—",
                                "Value": specs.get(
                                    listed_field_names.get(
                                        s["aspect_name"].lower(), ""
                                    ),
                                    "",
                                ),
                            })
                        st.dataframe(
                            pd.DataFrame(req_rows),
                            use_container_width=True,
                            hide_index=True,
                        )

                    st.markdown(
                        f"### Recommended for this category "
                        f"({len(recommended)})"
                    )
                    if not recommended:
                        st.markdown("_None recorded._")
                    else:
                        import pandas as pd
                        rec_rows = []
                        for s in recommended:
                            present = (
                                s["aspect_name"].lower()
                                in listed_field_names
                            )
                            rec_rows.append({
                                "Field": s["aspect_name"],
                                "Present on listing": "✔" if present else "—",
                                "Value": specs.get(
                                    listed_field_names.get(
                                        s["aspect_name"].lower(), ""
                                    ),
                                    "",
                                ),
                            })
                        st.dataframe(
                            pd.DataFrame(rec_rows),
                            use_container_width=True,
                            hide_index=True,
                        )


# --------------------------------------------------------------------
# Footer
# --------------------------------------------------------------------

st.markdown("---")
st.markdown(
    '<div class="small-note">'
    "Bynari Insight is independent. It fetches public listing data from "
    "eBay on the user's behalf using its own developer credentials. "
    "It does not authenticate the user with eBay. Anything you type "
    "here is discarded when you close this tab."
    "</div>",
    unsafe_allow_html=True,
)
