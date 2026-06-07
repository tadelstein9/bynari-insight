# Privacy Policy

**Effective date:** April 24, 2026
**Last updated:** April 24, 2026

Bynari Insight is independent software that helps eBay sellers create listings that meet eBay's own ranking and compliance requirements. This page explains what the app does with your information, what it does not do, and the choices you have.

Plain English first. Legal and regulatory language where it matters.

---

## Who we are

Bynari Insight is developed by Tom Adelstein and Paul Perotti.

A dedicated contact address will be published on this page once the Bynari Insight domain email is live. Until then, privacy questions can be raised through the GitHub repository at https://github.com/tadelstein9/bynari-insight.

---

## The two apps this policy covers

**Bynari Insight Desktop.** A Python application you install on your own computer. It connects to your eBay seller account on your behalf, reads your listings, and helps you improve them. Everything it reads stays on your computer unless you choose to send it somewhere.

**Bynari Insight Web** (`bynari-insight.streamlit.app`). A hosted web app that walks new eBay sellers through preparing their first listing. It runs in your browser and talks to eBay's Taxonomy API to tell you what fields a category requires.

Different apps, same principles below.

---

## What we collect

### Bynari Insight Desktop

When you connect the Desktop app to eBay, it uses eBay's OAuth 2.0 flow. That means:

- You log in on eBay's own site, not ours. We never see your eBay password.
- eBay gives the app a time-limited access token. The token is stored on your computer, in a file only your user account can read.
- The app reads your listings, categories, and item specifics from eBay in order to analyze them and show you results.

Your listing data stays on your computer. We do not upload it to a Bynari Insight server. We do not have a Bynari Insight server that could receive it.

### Bynari Insight Web

The Streamlit app runs in your browser. When you use it:

- The questions you answer stay in the Streamlit session — a temporary memory that exists while your browser tab is open and is discarded when you close it.
- The app calls eBay's Taxonomy API to look up categories and required fields. Those calls go from Streamlit's servers to eBay's servers. eBay sees those calls; we do not log them with your identity attached.
- If you choose to sign in with your eBay account for personalized features, the OAuth flow works the same way as Desktop: eBay handles the login, we never see your password, and the access token lives only inside your session.

We do not require you to create a Bynari Insight account.

### Both apps — what eBay sees

Because both apps make API calls through Bynari Insight's registered eBay application, eBay's own systems log that the Bynari Insight application made certain API calls on behalf of certain users. That is standard for any eBay-integrated software. eBay's privacy policy governs what they do with that log data.

### Analytics

Streamlit Cloud provides basic traffic analytics (page views, approximate geographic region, browser type). These are aggregate numbers used to understand whether the app is working and being used. They are not tied to your eBay account or to anything you typed into the app.

We do not use third-party trackers, advertising pixels, or cross-site cookies.

---

## What we do not collect

- We do not collect or store your eBay password.
- We do not collect your buyers' names, addresses, emails, phone numbers, or payment information.
- We do not collect sales data, feedback data, or financial data from your eBay account.
- We do not sell, rent, or share user information with advertisers, data brokers, or marketing lists.
- We do not train AI models on the content of your listings.

---

## How we use what we collect

The only purpose is to make the apps work: analyze your listings, look up eBay's current requirements for a category, and show you results.

Specifically:

- **Your OAuth access token** is used only to make eBay API calls on your behalf, and only for the operations the app shows you it is performing.
- **The answers you type into the Web app** are used only within your browser session to produce a draft listing you can copy and paste.
- **Search-count data from eBay's Taxonomy API** — once our App Check ticket for the `metadata.insights` scope is approved — is aggregate buyer-interest data at the category-and-field level. It contains no information about individual buyers.

We do not profile you, target you, score you, or sell anything we learn about you.

---

## Where your data lives

- **Desktop app:** on your computer. In the default install, credentials are stored under your operating system user directory.
- **Web app session data:** in Streamlit Cloud memory for the duration of your browser session. When you close the tab or the session times out, the data is gone.
- **Bynari Insight itself:** we do not operate a database of user data. There is nothing to breach.

---

## Third parties

Three parties are in the loop by virtue of how the software works. We have no control over their policies.

- **eBay, Inc.** — the API provider. Governed by eBay's User Privacy Notice.
- **Streamlit Cloud** (a Snowflake company) — the host for the Web app. Governed by Snowflake's privacy policy.
- **Your AI tool of choice** — the Web app produces a copy-pasteable prompt bundle that you, the user, can feed into Claude, ChatGPT, Copilot, or Gemini if you want help writing the listing text. If you do that, your chosen AI provider receives whatever you paste. We are not in that exchange. Their privacy policy applies.

---

## Your choices

- **Disconnect at any time.** In eBay's account settings, under "Apps you've connected," you can revoke Bynari Insight's access. The next API call from the app will fail cleanly; you can reconnect or not.
- **Uninstall the Desktop app** — delete the application folder and the credentials file. Nothing is left behind on any Bynari Insight-controlled system, because there is no Bynari Insight-controlled system holding your data.
- **Close the browser tab** for the Web app. Session data is discarded.
- **Raise an issue on GitHub** if you have questions, until the Bynari Insight domain contact address is live.

---

## Children

Bynari Insight is built for eBay sellers. eBay requires users to be 18 or older. We do not direct either app to children and do not knowingly collect information from anyone under 18.

---

## Changes to this policy

If we change how either app handles information, we will update this page and the "Last updated" date at the top. If a change is material — meaning it affects what is collected or how it is used — we will note it prominently here for at least 30 days before it takes effect.

---

## Legal basis and rights

For users in the **European Union / EEA / United Kingdom:** the legal basis for processing under GDPR is consent (you connect the app) and legitimate interest (making the app function for the purpose you asked for). You have the rights of access, correction, deletion, restriction, portability, and objection. Given how little data the apps actually hold, most of these requests resolve by pointing out that the data is on your own computer or was never retained.

For users in **California:** the California Consumer Privacy Act (CCPA / CPRA) gives you the right to know what is collected, to request deletion, and to opt out of sale or sharing. We do not sell or share personal information for cross-context behavioral advertising. See above for what is collected.

For users in **Texas, Virginia, Colorado, Connecticut, Utah, and other U.S. states** with consumer privacy laws: equivalent rights apply.

