import streamlit as st
import openai
import time
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import secrets
import json  # for JSON serialization
import numpy as np

# -------------------------------
# CONFIG: Similarity threshold & embedding model
# -------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"
SIMILARITY_THRESHOLD = 0.65  # adjust up/down to be stricter/looser

# -------------------------------
# BRAND COLORS & FONT
# -------------------------------
COLOR_DARK_BLUE = "#0F122B"
COLOR_PRIMARY_BLUE = "#21255F"
COLOR_LIGHT_BLUE = "#D0D1EA"
COLOR_BUTTON_TEXT = "#FFFFFF"
PRIMARY_FONT = "Arial, Helvetica, sans-serif"

# -------------------------------
# ENV LOAD
# -------------------------------
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = st.secrets["SUPABASE_SERVICE_KEY"]
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]

SMTP_HOST = st.secrets["SMTP_HOST"]
SMTP_PORT = st.secrets["SMTP_PORT"]
SMTP_USER = st.secrets["SMTP_USER"]
SMTP_PASS = st.secrets["SMTP_PASS"]
FROM_EMAIL = st.secrets["FROM_EMAIL"]

WELCOME_EMAIL_SUBJECT = "Welcome to AskTheBridge"
WELCOME_EMAIL_BODY = """Hi {email},

Welcome to AskTheBridge! We are very happy to have you onboard.


Warm regards,
The AskTheBridge Team
"""

VERIFICATION_EMAIL_SUBJECT = "Verify your AskTheBridge account"
VERIFICATION_EMAIL_BODY = """Hi {email},

Your verification code is: {code}
It is valid for 5 minutes.

The AskTheBridge Team
"""

PASSWORD_RESET_EMAIL_SUBJECT = "AskTheBridge Password Reset"
PASSWORD_RESET_EMAIL_BODY = """Hi {email},

Your password reset code is: {code}
It is valid for 10 minutes.

The AskTheBridge Team
"""

# -------------------------------
# SUPABASE CLIENT
# -------------------------------
if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not OPENAI_API_KEY:
    st.error("Missing environment variables for Supabase or OpenAI.")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
openai.api_key = OPENAI_API_KEY

# -------------------------------
# PAGE CONFIG
# -------------------------------
st.set_page_config(page_title="AskTheBridge", page_icon="🛥️", layout="wide")

# -------------------------------
# CUSTOM CSS
# -------------------------------
st.markdown(f"""
<style>
html, body, [class*="css"] {{
    font-family: {PRIMARY_FONT};
    background-color: #FFFFFF;
    color: {COLOR_LIGHT_BLUE};
}}
.stButton>button {{
    background-color: {COLOR_PRIMARY_BLUE};
    color: {COLOR_BUTTON_TEXT};
    border-radius: 10px;
    height: 40px;
    padding: 0 20px;
    font-weight: bold;
    margin: 5px 0;
}}
.stButton>button:hover {{
    background-color: {COLOR_LIGHT_BLUE};
    color: {COLOR_DARK_BLUE};
}}
h2, h3, h4 {{
    color: {COLOR_LIGHT_BLUE};
}}
.chat-container {{
    max-width: 800px;
    margin: auto;
    padding: 10px;
    background-color: transparent;
    border-radius: 15px;
    overflow: hidden;
}}
.chat-user {{
    background-color: rgba(33, 37, 95, 0.8);
    color: #FFFFFF;
    padding: 12px 15px;
    border-radius: 15px 15px 0 15px;
    margin: 8px 0;
    width: fit-content;
    max-width: 70%;
    float: right;
    clear: both;
}}
.chat-bot {{
    background-color: rgba(208, 209, 234, 0.85);
    color: #0F122B;
    padding: 12px 15px;
    border-radius: 15px 15px 15px 0;
    margin: 8px 0;
    width: fit-content;
    max-width: 70%;
    float: left;
    clear: both;
}}
.carousel-container {{
    overflow:hidden;
    width:100%;
    display:flex;
    justify-content:center;
    margin-bottom: 20px;
}}
.carousel-track {{
    display:flex;
    animation: scroll 20s linear infinite;
}}
.carousel-track img {{
    height: 80px;
    margin: 0 20px;
    transition: transform 0.3s;
}}
.carousel-track img:hover {{
    transform: scale(1.2);
}}
.split-answer {{
    display:flex; gap:20px;
}}
.split-left {{
    flex:1; padding-right:10px;
    background-color: rgba(208, 209, 234, 0.12);
    padding:10px;
    border-radius:10px;
}}
.split-right {{
    flex:1; padding-left:10px;
    background-color: rgba(33, 37, 95, 0.03);
    padding:10px;
    border-radius:10px;
}}

/* Make horizontal Streamlit columns really tight for buttons */
div[data-testid="stHorizontalBlock"] > div {{
    gap: 2px !important;  /* very small horizontal gap */
}}

/* Remove internal column padding for tighter buttons */
div[data-testid="stVerticalBlock"] > div {{
    padding: 0 !important;
}}
</style>
""", unsafe_allow_html=True)


# -------------------------------
# SESSION STATE INIT
# -------------------------------
if "page" not in st.session_state:
    st.session_state.page = "login"
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "users" not in st.session_state:
    st.session_state.users = {}  # {email: [ { "title": ..., "messages": [...] }, ... ] }
if "verification_codes" not in st.session_state:
    st.session_state.verification_codes = {}
if "password_reset_codes" not in st.session_state:
    st.session_state.password_reset_codes = {}
if "reset_step" not in st.session_state:
    st.session_state.reset_step = 1
if "partner_cache" not in st.session_state:
    st.session_state.partner_cache = None
if "current_chat_index" not in st.session_state:
    st.session_state.current_chat_index = None
if "feedback" not in st.session_state:
    st.session_state.feedback = []

# -------------------------------
# EMAIL FUNCTIONS
# -------------------------------
def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        st.error(f"Failed to send email: {e}")
        return False

def send_verification_code(email):
    code = secrets.token_hex(3)
    expiry = datetime.utcnow() + timedelta(minutes=5)
    st.session_state.verification_codes[email] = (code, expiry)
    body = VERIFICATION_EMAIL_BODY.format(email=email, code=code)
    return send_email(email, VERIFICATION_EMAIL_SUBJECT, body)

def send_password_reset_code(email):
    code = secrets.token_hex(3)
    expiry = datetime.utcnow() + timedelta(minutes=10)
    st.session_state.password_reset_codes[email] = (code, expiry)
    body = PASSWORD_RESET_EMAIL_BODY.format(email=email, code=code)
    return send_email(email, PASSWORD_RESET_EMAIL_SUBJECT, body)

def verify_code(email, code):
    if email in st.session_state.verification_codes:
        saved_code, expiry = st.session_state.verification_codes[email]
        if datetime.utcnow() > expiry:
            return False, "Verification code expired"
        if code == saved_code:
            del st.session_state.verification_codes[email]
            return True, "Verified"
    return False, "Invalid verification code"

def verify_reset_code(email, code):
    if email in st.session_state.password_reset_codes:
        saved, expiry = st.session_state.password_reset_codes[email]
        if datetime.utcnow() > expiry:
            return False, "Reset code expired"
        if code == saved:
            del st.session_state.password_reset_codes[email]
            return True, "Code verified"
    return False, "Invalid reset code"

# -------------------------------
# SUPABASE AUTH & DB FUNCTIONS
# -------------------------------
def supabase_sign_up(email, password):
    try:
        response = supabase.auth.sign_up({"email": email, "password": password})
        if response.user:
            log_user_activity(email, "signup")
            return {"email": email}
        else:
            st.error(response.message or "Signup failed.")
            return None
    except Exception as e:
        st.error(f"Signup error: {e}")
        return None

def supabase_sign_in(email, password):
    if not email or not password:
        st.error("Please provide both email and password.")
        return None
    try:
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if response.user:
            log_user_activity(email, "login")
            return {"email": email}
        else:
            st.error(response.message or "Invalid email or password.")
            return None
    except Exception as e:
        st.error(f"Sign in error: {e}")
        return None

def supabase_update_password(email, new_password):
    try:
        response = supabase.auth.update_user({"password": new_password})
        if response.user:
            log_user_activity(email, "password_reset")
            return True
        else:
            st.error("Could not update password.")
            return False
    except Exception as e:
        st.error(f"Error during password update: {e}")
        return False

def log_user_activity(user_email, action):
    try:
        supabase.table("user_activity").insert({
            "user_email": user_email,
            "action": action,
            "timestamp": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        st.error(f"Failed to log activity: {e}")

def save_chat_to_db(user_email, chat):
    try:
        supabase.table("user_chats").upsert([{
            "user_email": user_email,
            "chat_title": chat["title"],
            "messages": chat["messages"],
            "updated_at": datetime.utcnow().isoformat(),
        }], on_conflict="user_email,chat_title").execute()
    except Exception as e:
        st.error(f"Failed to save chat: {e}")

def load_chats_from_db(user_email):
    try:
        resp = supabase.table("user_chats").select("*").eq("user_email", user_email).order("created_at", {"ascending": True}).execute()
        chats = []
        for row in resp.data:
            chats.append({
                "title": row["chat_title"],
                "messages": row["messages"]
            })
        return chats
    except Exception as e:
        st.error(f"Failed to load chats: {e}")
        return []

# -------------------------------
# OPENAI / PARTNER LOGIC
# -------------------------------
@st.cache_data(show_spinner=False)
def ask_openai_cached(question: str):
    for attempt in range(3):
        try:
            response = openai.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.7,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant about yachting and technology."},
                    {"role": "user", "content": question},
                ],
            )
            return getattr(response.choices[0].message, "content", response.choices[0].message).strip()
        except Exception as e:
            err = str(e)
            if "rate limit" in err.lower() or "429" in err:
                time.sleep(5 * (attempt + 1))
                continue
            return f"⚠️ Error: {err}"
    return "⚠️ The system is receiving too many requests right now. Please try again in a few seconds."

# -------------------------------
# Embedding helpers
# -------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"  # optional if using embeddings

def compute_embedding(text: str):
    try:
        return None
    except Exception as e:
        st.warning(f"Embedding failed: {e}")
        return None

# -------------------------------
# Load partner Q&A cache
# -------------------------------
def load_partner_cache():
    if st.session_state.partner_cache is None:
        st.session_state.partner_cache = []

        qa_pairs = [
            {
                "question": "My chief stew and chef are in conflict two days before a busy charter. How do I de-escalate this without taking sides or compromising service?",
                "answer": "Speak to each individually first: listen, clarify facts, and separate emotion from concrete issues (menus, timing, storage, service style). "
                          "Restate the shared mission: 'Our job for the next 7 days is to deliver a seamless guest experience; we can revisit personal frustrations after the trip.' "
                          "Agree on minimum operating rules: service times, handover points, communication channel (e.g. one WhatsApp group, no side channels for ops). "
                          "Put a simple, written charter schedule in place (service times, special events, provisioning deadlines) and confirm they both sign off. "
                          "Monitor closely during the first 24 hours of charter and give specific positive feedback when collaboration works ('That breakfast turn-around was spot on, thanks to both of you.')."
            },
            {
                "question": "My rotation and leave plan looked fine on paper, but every season I end up with either short-staffing or burnout. What’s a better way to plan rotations?",
                "answer": "Start from guest program + maintenance, not from crew headcount: map peak periods, shipyard periods, crossings, owner weeks, and charters. "
                          "Build a 12-month coverage matrix: for each month, define minimum safe manning by department (bridge, interior, deck, engineering, galley). "
                          "Add buffer capacity around refit/yard and long crossings; these are the highest fatigue zones. "
                          "Use rotation templates (e.g. 2:2, 3:1) but adapt per department; engineers and chefs often need different patterns than deck. "
                          "Run a stress-test: mark months where >30–35% of the crew are 'new'—if that happens in peak guest periods, adjust hiring or contract dates."
            },
            {
                "question": "We’re about to switch from private to charter under a different flag. What are the most common compliance pitfalls captains miss in that transition?",
                "answer": "Safety equipment & certification: ensure all lifesaving appliances, fire systems and documentation match commercial requirements (not just private). "
                          "ISM/ISPS documentation: verify Safety Management System, drills records, and security plans are current and aligned with the new flag/management company. "
                          "Working/rest hours: move from 'owner-flexible' to strictly recorded MLC compliance; audit your last 3 months to avoid surprises at inspection. "
                          "Crew qualifications: check each role’s minimum safe manning certificate and endorsements for commercial operation. "
                          "Commercial paperwork: charter contracts, VAT handling, passenger limits – coordinate early with management, broker and legal so you’re aligned before the first charter."
            },
            {
                "question": "Port State Control and flag inspectors always seem to find something different. How can I prepare for inspections in a way that’s consistent and less stressful for the crew?",
                "answer": "Keep a simple inspection folder (digital + physical) with: certificates, last inspection report, corrective actions, crew lists, drills records and key checklists. "
                          "Run internal mini-inspections monthly: focus on basic items—LSA, FFA, signage, doors/vents, muster lists, logbooks. "
                          "Involve crew in the process: assign each head of department 3–5 common findings and make them responsible for 'owning' those areas. "
                          "After each real inspection, run a short 'lessons learned' debrief and update your checklist; treat it as continuous improvement, not blame. "
                          "Maintain a calm, transparent tone with inspectors; when they see the ship is organised and cooperative, inspections tend to be smoother."
            },
            {
                "question": "Our planned maintenance system is up to date on paper, but we still get nasty surprises in-season (AC failures, sewage issues, stabilisers). What can we change?",
                "answer": "Separate “compliance maintenance” (things you must log) from “reliability maintenance” (things that actually ruin a trip when they fail). "
                          "Build a “Top 20 Critical Failures” list for your yacht (AC, sewage, stabilisers, generators, tenders, galley key equipment) and add extra inspections there. "
                          "Use data from past seasons: which systems failed and when? Increase inspection frequency and spares holding for those items. "
                          "Before peak season, run a Red Team walk-through with engineer + chief stew + deck: ask “What would ruin a guest day if it broke right now?” and act on it. "
                          "Track not just completed tasks, but unplanned downtime; aim to reduce that season-on-season."
            },
            {
                "question": "I’m choosing between several refit yards for a big paint and machinery job. Beyond the quote, what should I really look at?",
                "answer": "Check yard track record with your size and type of vessel—ask for 2–3 recent captains you can speak to directly. "
                          "Evaluate project management structure: is there a dedicated PM assigned, with clear communication routines and reporting formats? "
                          "Assess logistics & location (flights, crew housing, visa, weather windows) and include those costs/risks in your comparison. "
                          "Review quality control processes: acceptance criteria, warranty terms, and how disputes are handled. "
                          "Visit if possible: walk the yard, look at housekeeping, safety culture and how work is organised; these soft signals often matter more than the brochure."
            },
            {
                "question": "Owner wants a “different” Med season with fewer crowded ports and more unique anchorages, but we must stay safe and practical. How do I approach this?",
                "answer": "Start with constraints: yacht draft/LOA, helicopter ops, guest ages, mobility, and any security concerns. "
                          "Map secondary hubs within each region (e.g. alternatives to St Tropez/Capri/Mykonos) that still have decent provisioning and medical access. "
                          "Use past AIS and port call data (yours and comparable yachts if available) to avoid patterns everyone else follows. "
                          "Plan “hero moments” (1–2 special anchorages or off-grid stops) backed by solid weather and escape plans. "
                          "Present the owner with 2–3 curated itineraries that balance uniqueness with realism—highlighting exactly why each feels different from a classic milk run."
            },
            {
                "question": "We’re under pressure to reduce fuel burn but still maintain ambitious itineraries. What are some practical routing strategies I can use?",
                "answer": "Optimise transit speeds: small reductions (e.g. from 14 to 11–12 knots) often save disproportionate fuel over a season. "
                          "Plan shorter legs with more local clusters of experiences instead of long daily hops. "
                          "Use weather and current routing to minimise head seas and adverse conditions where possible. "
                          "Coordinate with the owner/charter broker early to align expectations: show a fuel-optimised itinerary vs a “max distance” one. "
                          "Log fuel burn vs itinerary in a simple dashboard and share trends with the owner/management; this makes future compromises easier to negotiate."
            },
            {
                "question": "We get very little information about guest preferences before charters. How can I still deliver a personalised experience without annoying the broker or PA?",
                "answer": "Create a simple, visually appealing preference sheet that brokers actually want to forward—less text, more checkboxes and examples. "
                          "Ask for categories rather than specifics: dietary limits, general food styles, activity level, nightlife vs quiet, kids vs adults focus. "
                          "Prepare modular experiences: a few ready-to-go “themes” (wellness day, water sports day, local culture day, party night) you can adapt on the fly. "
                          "Use the first 12–24 hours to quietly observe and adjust: meal portions, timing, music volume, favourite spots onboard. "
                          "Debrief with the broker post-charter, sharing what worked well; over time, that builds a richer picture for repeat clients."
            },
            {
                "question": "The owner’s friends often show up last-minute with no notice. How can I build flexibility into the program without burning out the crew?",
                "answer": "Define a “surge plan” with your HoDs: what changes when guest count spikes (service style, turndown, menu complexity, tender schedule). "
                          "Maintain a basic backup provisioning list with easy, high-quality options that can scale guest numbers quickly. "
                          "Protect crew core rest hours by temporarily reducing non-critical tasks (deep detailing, non-urgent maintenance) during these spikes. "
                          "Communicate clearly with the owner/PA about what can and can’t be done last-minute without compromising safety. "
                          "After each event, review impact on crew fatigue and adjust your surge plan for next time."
            },
            {
                "question": "Our operating budget is always blown by the end of the season, especially in maintenance and provisions. How can I make the numbers more predictable?",
                "answer": "Break the budget into 4–6 clear buckets (fuel, port/marina, maintenance, provisions, crew, “owner requests”) with monthly caps. "
                          "Track “unplanned” vs “planned” spend separately; unplanned is where you’ll find improvement opportunities. "
                          "Use last 2–3 seasons’ actuals to build a more realistic baseline, then add a defined contingency (e.g. 10–15%) rather than pretending it won’t be used. "
                          "Share a simple monthly one-pager with the owner/management: big spends, savings and reasons; that builds trust and makes future conversations easier. "
                          "Make at least one small visible saving initiative per season (e.g. shorepower vs generators where feasible) and show the numbers."
            },
            {
                "question": "Management is cutting the maintenance budget, but I’m worried we’ll pay more later. How do I argue this without sounding difficult?",
                "answer": "Translate technical risk into owner-language: tie maintenance cuts directly to “chance of losing charter days” or “trip disruption risk.” "
                          "Present scenarios: “If we defer X, probability of failure in season is roughly Y; cost of that failure (lost days + emergency yard time) is Z.” "
                          "Identify low-impact cuts you can accept (cosmetics, non-critical upgrades) to show you’re being cooperative. "
                          "Propose a phased plan: what you must do this year, what can safely be postponed, and what should be monitored closely. "
                          "Keep the tone solution-oriented: “Here are 3 options; my professional recommendation is B.”"
            },
            {
                "question": "My owner changes his mind frequently about plans and priorities. How do I manage this without constant chaos on board?",
                "answer": "Introduce a simple planning rhythm: e.g. a weekly brief (written or call) where you confirm itinerary, key priorities and any constraints. "
                          "Summarise decisions back to the owner/PA after each change: “To confirm, we now do X instead of Y, which means Z impact.” "
                          "Internally, maintain a “stable core” (safety, maintenance, compliance) that doesn’t move, and treat rest as flexible. "
                          "Build a reputation for being both adaptable and transparent: say “yes” when you can, and clearly explain trade-offs when you can’t. "
                          "Document major changes in a simple log; this helps avoid blame later and supports your case in future discussions."
            },
            {
                "question": "Management company and I don’t always see eye to eye. How do I keep the relationship constructive but protect the vessel’s interests?",
                "answer": "Clarify roles and responsibilities in writing: who decides on what (crew, budget, routing, major works, vendors). "
                          "Use a regular standing call (e.g. bi-weekly) with a fixed agenda: safety, operations, finance, owner feedback, upcoming decisions. "
                          "When you disagree, separate facts, risks and opinions; propose options with pros/cons rather than “yes/no.” "
                          "Copy in the right people (e.g. DPA, fleet manager) for issues that affect compliance and safety – that frames it as a professional concern. "
                          "Keep your tone consistently calm and professional; over time, being the person who brings structured information and solutions increases your influence."
            },
            {
                "question": "We had a black water failure during charter—nightmare. What can I implement so this never happens again during a guest trip?",
                "answer": "Treat black water and grey water as “mission critical”: review design limits, tank capacities, pump redundancy and venting. "
                          "Implement pre-charter stress tests: simulate full guest load, run all heads, showers and laundry to confirm flows are stable. "
                          "Create usage guidelines for guests (discreet, elegant signage + crew script) to reduce abuse. "
                          "Maintain a spares & tools kit specifically for sewage systems and ensure crew are trained to use it. "
                          "Review with an external specialist after the season if failures persist; design fixes are often cheaper than repeated emergencies."
            },
            {
                "question": "Our stabilisers have become the most unreliable part of the vessel. How do I decide whether to keep repairing or plan for a bigger upgrade?",
                "answer": "Log every incident with date, sea state, mode, and impact on guest comfort; patterns matter. "
                          "Discuss with OEM/service partner: ask for a clear view of expected life, known failure modes and upgrade paths. "
                          "Cost out the last 2–3 seasons of call-outs, downtime and lost guest days versus an overhaul/upgrade. "
                          "Consider future itinerary (more crossings? rougher seas?) when evaluating risk. "
                          "Present management/owner with options (maintain vs major upgrade) including financial and operational implications."
            },
            {
                "question": "I’m a first-time captain on a 50–60m. What are the first 3 systems or processes I should review in detail in my first 90 days?",
                "answer": "Safety & compliance: SMS, muster lists, drills records, equipment certificates, and how crew actually behave in drills. "
                          "Maintenance & critical systems: PMS setup, spares strategy, and condition of generators, stabilisers, sewage, AC and tenders. "
                          "Crew structure & culture: rotations, handover quality, communication routines, and the captain–HoD leadership dynamic. "
                          "Make a 90-day plan with 3–5 concrete improvements and review it with management/owner’s rep to align expectations."
            },
            {
                "question": "Owner wants “more use” of the yacht but crew are already stretched. How do I safely increase days in use without losing people or breaking the boat?",
                "answer": "Quantify current vs requested days in use and overlay maintenance windows; show where pressure points occur. "
                          "Propose a phased increase (e.g. +20% days this year) and define what support changes are needed (extra crew, different rotations, bigger maintenance yard period). "
                          "Use data from past seasons (unplanned downtime, sick days, crew turnover) as arguments, not feelings. "
                          "Suggest “smart” extra use (shoulder seasons, off-peak charters) rather than stacking more into already crowded months. "
                          "Agree in writing on minimum maintenance and rest periods that must remain untouched."
            },
            {
                "question": "How can I use data from our operations to have better conversations with the owner about risk, cost and upgrades?",
                "answer": "Start small: track 3–5 metrics consistently (days in use, unplanned downtime incidents, fuel burn, major unplanned costs, crew turnover). "
                          "Present these visually in a simple quarterly one-pager. "
                          "Use that sheet to frame conversations: “We did X days, had Y incidents, Z unplanned cost – here’s what I recommend for next season.” "
                          "Link upgrade requests directly to those metrics (e.g. “If we upgrade X, we expect fewer incidents like Y, which cost us €…”). "
                          "Over time, this shifts conversation from opinions to trend-based decisions."
            },
            {
                "question": "We’re constantly reactive. Is there a simple operational rhythm I can install so the boat feels more in control and less firefighting?",
                "answer": "Implement a weekly operations meeting with HoDs: last week’s key issues, coming week’s plan, risks and guest highlights. "
                          "Add a monthly “big picture” review: budget, maintenance, crew wellbeing, upcoming refit or major changes. "
                          "Use a shared action list (even a simple spreadsheet) with owners, deadlines and status so nothing is just “in someone’s head.” "
                          "Reserve protected time in the calendar for drills, training and preventative checks – don’t let them be the first thing cancelled. "
                          "Stick to this rhythm even in quiet times; consistency is what builds a less reactive culture."
            }
        ]

        # Save to session_state
        for pair in qa_pairs:
            st.session_state.partner_cache.append({
                "question": pair["question"],
                "answer": pair["answer"],
                "embedding": None
            })

load_partner_cache()
STATIC_QA = {pair["question"].lower(): pair["answer"] for pair in st.session_state.partner_cache}

def get_answer(user_input: str):
    key = user_input.strip().lower()
    if key in STATIC_QA:
        return STATIC_QA[key]   # static answer
    return ask_openai_cached(user_input)

# -------------------------------
# CHAT HANDLING AND RENDERING
# -------------------------------
# -------------------------------
# CHAT HANDLING AND RENDERING
# -------------------------------
def render_chat(messages):
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)

    for idx, msg in enumerate(messages):
        if msg["role"] == "user":
            st.markdown(f'<div class="chat-user">{msg["content"]}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="chat-bot">{msg["content"]}</div>', unsafe_allow_html=True)

            # Show static answer buttons only for static answers
            if msg.get("is_static_answer"):
                container = st.container()
                with container:
                    cols = st.columns(4, gap="small")
                    buttons = ["Ask a Specialist", "Ask Your Peers", "Ask on Instagram", "Ask OpenAI"]
                    for i, button_text in enumerate(buttons):
                        with cols[i]:
                            if st.button(button_text, key=f"{button_text}_{idx}"):
                                if button_text == "Ask OpenAI":
                                    # Call OpenAI only when button clicked
                                    ai_response = ask_openai_cached(msg["content"])
                                    # Insert new AI response right after the static answer
                                    messages.insert(idx + 1, {"role": "bot", "content": ai_response})
                                    # Save updated chat to DB
                                    save_chat_to_db(
                                        st.session_state.username,
                                        {
                                            "title": st.session_state.users[st.session_state.username][
                                                st.session_state.current_chat_index
                                            ]["title"],
                                            "messages": messages
                                        }
                                    )
                                else:
                                    st.info(f"You clicked '{button_text}'")
    st.markdown('</div>', unsafe_allow_html=True)


# UI: LOGIN / SIGNUP / VERIFICATION / RESET PAGES
# (kept same as your original)
# -------------------------------
def show_login_page():
    st.markdown("<h2 style='text-align:center;'>Welcome to AskTheBridge 🛥️</h2>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Sign In")
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        def login():
            user = supabase_sign_in(email, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.username = email
                # Load chats
                st.session_state.users[email] = load_chats_from_db(email)
                # Set default chat index
                if len(st.session_state.users[email]) == 0:
                    st.session_state.users[email].append({"title": "Chat 1", "messages": []})
                st.session_state.current_chat_index = 0
                st.session_state.page = "chat"

        st.button("Sign In", key="login_btn", on_click=login)

        if st.button("Forgot Password?"):
            st.session_state.page = "reset_password"
            st.session_state.reset_step = 1

        # Guest login
        def guest_login():
            st.session_state.logged_in = True
            st.session_state.username = "Guest"
            if "Guest" not in st.session_state.users:
                st.session_state.users["Guest"] = [{"title": "Chat 1", "messages": []}]
            st.session_state.current_chat_index = 0
            st.session_state.page = "chat"

        st.button("Continue as Guest", key="guest_btn", on_click=guest_login)

    with col2:
        st.subheader("Create an Account")
        new_email = st.text_input("Email", key="signup_email")
        new_password = st.text_input("Password", type="password", key="signup_password")

        def signup():
            if not new_email or not new_password:
                st.error("Provide email & password")
            else:
                if send_verification_code(new_email):
                    st.session_state.page = "verify"
                    st.session_state.temp_signup_email = new_email
                    st.session_state.temp_signup_password = new_password
                    st.success("Verification code sent!")

        st.button("Sign Up", on_click=signup)

def show_verification_page():
    email = st.session_state.temp_signup_email
    password = st.session_state.temp_signup_password
    code = st.text_input("Enter verification code sent to your email", key="verify_code")

    def verify():
        valid, msg = verify_code(email, code)
        if valid:
            user = supabase_sign_up(email, password)
            if user:
                send_email(email, WELCOME_EMAIL_SUBJECT, WELCOME_EMAIL_BODY.format(email=email))
                st.success("Account verified! You can now log in.")
                st.session_state.page = "login"
            else:
                st.error("Signup failed.")
        else:
            st.error(msg)

    st.button("Verify", on_click=verify)

def show_reset_password_page():
    st.markdown("<h3>Reset Your Password</h3>", unsafe_allow_html=True)
    step = st.session_state.reset_step

    if step == 1:
        reset_email = st.text_input("Email", key="reset_email")
        if st.button("Send Reset Code"):
            if not reset_email:
                st.error("Enter your email")
            else:
                if send_password_reset_code(reset_email):
                    st.session_state.reset_step = 2
                    st.session_state.reset_email_temp = reset_email  # use a different key
                    st.success("Reset code sent! Check your email.")

    elif step == 2:
        code = st.text_input("Reset Code", key="reset_code")
        new_password = st.text_input("New Password", type="password", key="reset_new_password")
        if st.button("Reset Password"):
            email_to_reset = st.session_state.reset_email_temp
            valid, msg = verify_reset_code(email_to_reset, code)
            if valid:
                success = supabase_update_password(email_to_reset, new_password)
                if success:
                    st.success("Password reset successfully! You can now log in.")
                    st.session_state.page = "login"
                    st.session_state.reset_step = 1
                else:
                    st.error("Could not reset password.")
            else:
                st.error(msg)

    if st.button("Back to Login"):
        st.session_state.page = "login"
        st.session_state.reset_step = 1

# -------------------------------
# CHAT PAGE
# -------------------------------
def show_chat_page():
    user_email = st.session_state.username
    if user_email not in st.session_state.users:
        st.session_state.users[user_email] = [{"title": "Chat 1", "messages": []}]
    user_chats = st.session_state.users.get(user_email, [])

    with st.sidebar:
        st.markdown("### ⚙️ Chat Options")
        if st.button("⬅️ Logout"):
            st.session_state.page = "login"
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.current_chat_index = None
            st.stop()
        if st.button("🆕 New Chat"):
            new_title = f"Chat {len(user_chats) + 1}"
            user_chats.append({"title": new_title, "messages": []})
            st.session_state.current_chat_index = len(user_chats) - 1
        st.markdown("### Previous Chats")
        for idx, chat in enumerate(user_chats):
            if st.button(chat["title"], key=f"chat_{idx}"):
                st.session_state.current_chat_index = idx

    if st.session_state.current_chat_index is None:
        st.session_state.current_chat_index = 0

    current_chat = user_chats[st.session_state.current_chat_index]

    st.markdown(f"<p style='text-align:center;'>Logged in as: <b>{user_email}</b> | Chat: <b>{current_chat['title']}</b></p>", unsafe_allow_html=True)

    placeholder_logos = [
        "https://via.placeholder.com/150?text=Partner+1",
        "https://via.placeholder.com/150?text=Partner+2",
        "https://via.placeholder.com/150?text=Partner+3",
        "https://via.placeholder.com/150?text=Partner+4"
    ]

    carousel_html = '<div class="carousel-container"><div class="carousel-track">'
    for logo_url in placeholder_logos:
        carousel_html += f'<img src="{logo_url}" alt="Partner logo">'
    carousel_html += '</div></div>'
    st.markdown(carousel_html, unsafe_allow_html=True)

    chat_container = st.container()
    input_container = st.container()

    with input_container:
        with st.form(key="chat_form", clear_on_submit=True):
            cols = st.columns([4, 1])
            user_input = cols[0].text_input("", placeholder="Type your message...")
            submitted = cols[1].form_submit_button("Send")
            if submitted and user_input.strip() != "":
                current_chat["messages"].append({"role": "user", "content": user_input.strip()})
                key = user_input.strip().lower()
                if key in STATIC_QA:
                    answer = STATIC_QA[key]
                    current_chat["messages"].append({"role": "bot", "content": answer, "is_static_answer": True})
                else:
                    ai_response = ask_openai_cached(user_input.strip())
                    current_chat["messages"].append({"role": "bot", "content": ai_response})
                save_chat_to_db(user_email, {"title": current_chat["title"], "messages": current_chat["messages"]})

    with chat_container:
        render_chat(current_chat["messages"])

# -------------------------------
# MAIN
# -------------------------------
if not st.session_state.logged_in:
    if st.session_state.page == "login":
        show_login_page()
    elif st.session_state.page == "verify":
        show_verification_page()
    elif st.session_state.page == "reset_password":
        show_reset_password_page()
else:
    show_chat_page()
