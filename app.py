"""
Bynari Insight — Analyze a Listing (Streamlit web app)

A focused web tool: paste an eBay item number, get its public listing data
compared against the structural data Bynari holds for that category. The full
guided walkthrough lives at bynari-insight.com — this page serves the narrower
"I have an item number, just show me the specifics" impulse.

All data access (cassini.db categories, eBay Browse API) is mediated through
api.tadelstein.com. This app ships no data and holds no credentials.
"""

import streamlit as st
import pandas as pd
import requests

from pages_privacy import render as render_privacy


# --------------------------------------------------------------------
# Page config and styling
# --------------------------------------------------------------------

st.set_page_config(
    page_title="Bynari Insight — Analyze a Listing",
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
      .small-note {
        color: #666;
        font-size: 0.9rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------
# Privacy route (?page=privacy) — kept from the deploy skeleton
# --------------------------------------------------------------------

if st.query_params.get("page") == "privacy":
    render_privacy()
    st.stop()


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
        return None, "Couldn't parse the response from eBay."


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
# Required / recommended comparison table
# --------------------------------------------------------------------

def _specifics_table(specifics, listed_field_names, specs):
    rows = []
    for s in specifics:
        present = s["aspect_name"].lower() in listed_field_names
        rows.append({
            "Field": s["aspect_name"],
            "Present on listing": "✔" if present else "—",
            "Value": specs.get(
                listed_field_names.get(s["aspect_name"].lower(), ""),
                "",
            ),
        })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------
# Page: Analyze a Listing
# --------------------------------------------------------------------

st.title("Analyze a Listing")
st.write(
    "Paste an eBay item number below. Bynari fetches the listing's public "
    "data and compares it against the structural data we have for that "
    "category — what's required, what's recommended, what's missing."
)
st.info(
    "Looking for the full guided walkthrough — photos, category, comparable "
    "items, title, and description? Visit "
    "[bynari-insight.com](https://bynari-insight.com)."
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
                st.markdown(f"**Price:** {data['price']} {data['currency']}")
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
                    "eBay didn't return a category ID for this listing. "
                    "Comparison against Bynari's data is not possible "
                    "without it."
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
            has_condition = any(w in title.lower() for w in condition_words)
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
            st.markdown(f"### Item specifics on this listing ({len(specs)})")
            if not specs:
                st.markdown(
                    "_eBay didn't return any item specifics for this listing._"
                )
            else:
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
                listed_field_names = {k.lower(): k for k in specs.keys()}
                required = [s for s in cassini_specifics if s["required"]]
                recommended = [
                    s for s in cassini_specifics if not s["required"]
                ]

                st.markdown("---")
                st.markdown(f"### Required for this category ({len(required)})")
                if not required:
                    st.markdown("_None recorded._")
                else:
                    st.dataframe(
                        _specifics_table(required, listed_field_names, specs),
                        use_container_width=True,
                        hide_index=True,
                    )

                st.markdown(
                    f"### Recommended for this category ({len(recommended)})"
                )
                if not recommended:
                    st.markdown("_None recorded._")
                else:
                    st.dataframe(
                        _specifics_table(
                            recommended, listed_field_names, specs
                        ),
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
    "eBay on the user's behalf using its own developer credentials. It does "
    "not authenticate the user with eBay. Anything you type here is "
    "discarded when you close this page."
    "</div>",
    unsafe_allow_html=True,
)
st.caption("Built by Bynari. [Privacy policy](?page=privacy)")
