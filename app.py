"""
Bynari Insight — Streamlit web app
Independent structural reference data for eBay sellers.
"""

import base64
import io
import json
import re
import sqlite3
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
# cassini.db access
# --------------------------------------------------------------------

CASSINI_DB_PATH = "cassini.db"


@st.cache_resource
def get_cassini_connection():
    conn = sqlite3.connect(
        f"file:{CASSINI_DB_PATH}?mode=ro",
        uri=True,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    return conn


def category_lookup_by_id(category_id: str):
    conn = get_cassini_connection()
    row = conn.execute(
        "SELECT category_id, category_name, parent_id, full_path, leaf_category "
        "FROM categories WHERE category_id = ?",
        (str(category_id),),
    ).fetchone()
    return dict(row) if row else None


def category_lookup_by_name(name: str, limit: int = 5):
    """
    Find categories whose name or full_path matches the given string.
    Returns a list of dicts. Empty list if nothing matches.
    """
    if not name:
        return []
    conn = get_cassini_connection()
    # First try exact match on category_name
    rows = conn.execute(
        "SELECT category_id, category_name, parent_id, full_path, leaf_category "
        "FROM categories "
        "WHERE LOWER(category_name) = LOWER(?) AND leaf_category = 1 "
        "LIMIT ?",
        (name.strip(), limit),
    ).fetchall()
    if rows:
        return [dict(r) for r in rows]
    # Fall back to LIKE on category_name
    rows = conn.execute(
        "SELECT category_id, category_name, parent_id, full_path, leaf_category "
        "FROM categories "
        "WHERE LOWER(category_name) LIKE LOWER(?) AND leaf_category = 1 "
        "LIMIT ?",
        (f"%{name.strip()}%", limit),
    ).fetchall()
    if rows:
        return [dict(r) for r in rows]
    # Last resort: search full_path
    rows = conn.execute(
        "SELECT category_id, category_name, parent_id, full_path, leaf_category "
        "FROM categories "
        "WHERE LOWER(full_path) LIKE LOWER(?) AND leaf_category = 1 "
        "LIMIT ?",
        (f"%{name.strip()}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def item_specifics_for_category(category_id: str):
    conn = get_cassini_connection()
    specifics = conn.execute(
        "SELECT id, aspect_name, aspect_mode, required, data_type "
        "FROM item_specifics WHERE category_id = ? "
        "ORDER BY required DESC, aspect_name",
        (str(category_id),),
    ).fetchall()
    result = []
    for s in specifics:
        values = conn.execute(
            "SELECT value FROM allowed_values WHERE specific_id = ? ORDER BY value",
            (s["id"],),
        ).fetchall()
        result.append({
            "aspect_name": s["aspect_name"],
            "aspect_mode": s["aspect_mode"],
            "required": bool(s["required"]),
            "data_type": s["data_type"],
            "allowed_values": [v["value"] for v in values],
        })
    return result


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
# Bynari API (api.tadelstein.com) — used by Tab 3
# --------------------------------------------------------------------

BYNARI_API_URL = "https://api.tadelstein.com/item.php"


def fetch_listing(item_id: str):
    """
    Call the Bynari API endpoint for an item.
    Returns (data_dict, error_string). One will be None.
    """
    try:
        r = requests.get(
            BYNARI_API_URL,
            params={"item": item_id},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Bynari Insight Streamlit)"},
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
    except Exception as e:
        return None, f"Parse error: {type(e).__name__}: {e} | First 200 chars: {r.text[:200]}"


def translate_browse_response(api_data: dict) -> dict:
    """
    Translate eBay Browse API response into the shape the rendering
    code expects: title, specs (dict), catId, itemId.
    """
    # Item specifics live in localizedAspects as a list of
    # {name, value} dicts in Browse API. Flatten to a dict.
    specs = {}
    for aspect in api_data.get("localizedAspects") or []:
        name = aspect.get("name", "").strip()
        value = aspect.get("value", "").strip()
        if name and value:
            specs[name] = value

    # categoryIdPath is "58058|175673|27386" — leaf is the last one
    cat_id = ""
    cat_path = api_data.get("categoryIdPath", "")
    if cat_path:
        cat_id = cat_path.split("|")[-1]

    # itemId in Browse API is "v1|206276547370|0" — extract the middle
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
    """Datasheet for one category — used by Tab 1."""
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
    """
    Datasheet covering multiple categories — used by Tab 2.
    category_pairs is a list of (lqr_category_name, condition, resolved_cat_dict)
    where resolved_cat_dict may be None if cassini.db has no match.
    """
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
    st.header("Category datasheet")
    st.write(
        "Type what you're looking at. Open eBay in a new tab to find "
        "your category. Paste any eBay URL or category ID back into "
        "Bynari to get the structural data — required fields, "
        "recommended fields, allowed values — for that category."
    )

    col_a, col_b = st.columns([3, 1])
    with col_a:
        query = st.text_input(
            "Describe the item",
            placeholder="e.g., Crucial X8 NVMe SSD 1TB",
            key="t1_query",
        )
    with col_b:
        st.write("")
        st.write("")
        if query.strip():
            sold_url = build_ebay_search_url(query, sold=True)
            active_url = build_ebay_search_url(query, sold=False)
            st.link_button("See what sold ↗", sold_url,
                           use_container_width=True)
            st.link_button("See active listings ↗", active_url,
                           use_container_width=True)

    if query.strip():
        st.markdown(
            '<div class="small-note">eBay opens in a new tab in your '
            "own browser. Bynari does not visit eBay.</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    st.subheader("Generate the datasheet")
    st.write(
        "Paste any eBay URL from the tab you just opened (a search "
        "results URL, a listing URL, or a category page URL), or paste "
        "the numeric category ID."
    )

    pasted = st.text_input(
        "eBay URL or category ID",
        placeholder="https://www.ebay.com/sch/i.html?... or 175669",
        key="t1_paste",
    )

    if st.button("Generate datasheet", type="primary", key="t1_gen"):
        cat_id = extract_category_id(pasted)
        if cat_id is None:
            st.error(
                "Couldn't find a category ID in that. Paste an eBay URL "
                "that contains `_sacat=` in the query string, or just "
                "the numeric category ID."
            )
        else:
            cat = category_lookup_by_id(cat_id)
            if cat is None:
                st.error(
                    f"Category ID {cat_id} is not in Bynari's data."
                )
            else:
                doc = build_single_category_datasheet(
                    cat, query or "(no query entered)"
                )
                st.text_area(
                    "Category datasheet — copy this and hand it to your LLM",
                    value=doc,
                    height=600,
                    key="t1_output",
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
            # Categories the analyzer flagged at least one listing in
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

                # Resolve the category from cassini.db
                cat = None
                cat_id = data.get("catId", "")
                if cat_id:
                    cat = category_lookup_by_id(cat_id)

                # Header info
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

                # Title observations
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

                # Item specifics on listing
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

                # Compare against cassini.db if we have a category
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
