# Streamlit in Snowflake UI for the layer 1 interview. tools/build_app.py inlines python/interview.py
# above this file to produce app/interview_app.py, a single file you paste into Snowsight (no CLI, no
# stage upload). Run the app as role SVC_INTERVIEWER (sql/09_interview_setup.sql).
import time
import uuid

import streamlit as st
from snowflake.snowpark.context import get_active_session

MODEL = "CLAUDE-SONNET-5"
APP_SCHEMA = "SVC_APP.INTERVIEW"
RETRY_WAITS = (2, 5)          # AI_COMPLETE intermittently returns empty answers (ADR-013)
RECENT_TURNS = 8

session = get_active_session()


def ai_text(prompt, max_tokens=200):
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            raw = session.sql(
                f"SELECT AI_COMPLETE('{MODEL}', ?, {{'temperature': 0.2, 'max_tokens': {max_tokens}}})",
                params=[prompt]).collect()[0][0]
        except Exception:
            raw = None
        text = clean_reply(raw)
        if text:
            return text
        if attempt < len(RETRY_WAITS):
            time.sleep(RETRY_WAITS[attempt])
    return ""


def ai_extract(prompt):
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            raw = session.sql(
                f"SELECT AI_COMPLETE('{MODEL}', ?, {{'temperature': 0, 'max_tokens': 2048}}, "
                f"{{'type': 'json', 'schema': {schema_literal(EXTRACTION_SCHEMA)}}}, TRUE)",
                params=[prompt]).collect()[0][0]
            parsed = parse_structured(raw)
        except Exception:
            parsed = None
        if parsed is not None:
            return parsed
        if attempt < len(RETRY_WAITS):
            time.sleep(RETRY_WAITS[attempt])
    return None


def load_denylist():
    try:
        return [r[0] for r in session.sql(f"SELECT NAME FROM {APP_SCHEMA}.SCHEMA_DENYLIST").collect()]
    except Exception:
        return []


def save_turn(speaker, content):
    S = st.session_state
    session.sql(
        f"INSERT INTO {APP_SCHEMA}.INTERVIEW_TURNS SELECT ?, TRY_TO_NUMBER(?), ?, ?, CURRENT_TIMESTAMP()",
        params=[S.sid, str(len(S.turns)), speaker, content]).collect()


def save_draft(status):
    S = st.session_state
    session.sql(
        f"MERGE INTO {APP_SCHEMA}.TERM_DRAFTS t USING "
        "(SELECT ? AS DRAFT_ID, ? AS SESSION_ID, ? AS STATUS, PARSE_JSON(?) AS TERM) s "
        "ON t.DRAFT_ID = s.DRAFT_ID "
        "WHEN MATCHED THEN UPDATE SET STATUS = s.STATUS, TERM = s.TERM, UPDATED_AT = CURRENT_TIMESTAMP(), "
        "CONFIRMED_AT = IFF(s.STATUS = 'CONFIRMED', CURRENT_TIMESTAMP(), t.CONFIRMED_AT) "
        "WHEN NOT MATCHED THEN INSERT (DRAFT_ID, SESSION_ID, STATUS, TERM, CREATED_AT, UPDATED_AT) "
        "VALUES (s.DRAFT_ID, s.SESSION_ID, s.STATUS, s.TERM, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP())",
        params=[S.draft_id, S.sid, status, json.dumps(S.draft, ensure_ascii=False)]).collect()


def say(text):
    S = st.session_state
    S.turns.append({"speaker": "assistant", "content": text})
    save_turn("assistant", text)


def ask_next():
    S = st.session_state
    focus = next_focus(S.draft, tuple(S.asked_optional))
    if focus is None:
        S.stage, S.focus = "readback", None
        say("Thank you. Here is what I have. Please check it and tell me if anything is wrong.")
        return
    S.focus = focus
    S.asks[focus] = S.asks.get(focus, 0) + 1
    recent = "\n".join(f"{t['speaker'].upper()}: {t['content']}" for t in S.turns[-RECENT_TURNS:])
    question = ai_text(build_system_prompt(S.draft, focus) + "\n\nConversation so far:\n" + recent)
    if not question or find_schema_words(question, S.denylist):
        question = PROMPTS[focus]          # fixed fallback, always safe to show
    say(question)


def handle_user(text):
    S = st.session_state
    S.turns.append({"speaker": "user", "content": text})
    save_turn("user", text)
    if find_schema_words(text, S.denylist):
        say("That sounds like a technical name. Could you describe it in everyday business words instead?")
        return
    extracted = ai_extract(build_extraction_prompt(S.turns))
    if extracted:
        S.draft = merge_extraction(S.draft, extracted)
    if S.stage == "interview":
        focus = S.focus
        if focus in OPTIONAL:
            S.asked_optional.append(focus)
        elif focus in missing_fields(S.draft) and (extracted is None or S.asks.get(focus, 0) >= MAX_ASKS):
            S.draft = apply_focus_fallback(S.draft, focus, text)
    save_draft("DRAFT")
    if S.stage == "interview":
        ask_next()
    else:
        say("Thank you, I have updated the summary. Please check it again.")


S = st.session_state
if "sid" not in S:
    S.sid, S.draft_id = str(uuid.uuid4()), str(uuid.uuid4())
    S.turns, S.draft, S.asked_optional, S.asks = [], {}, [], {}
    S.stage, S.focus, S.denylist = "interview", None, load_denylist()
    S.focus = "term"
    S.asks["term"] = 1
    say("Hello. I will ask you a few questions about one business term, in your own words. "
        "You do not need to know anything about our data. " + PROMPTS["term"])

st.title("Tell us what a business term means")
with st.sidebar:
    st.subheader("Progress")
    gaps = missing_fields(S.draft)
    for f in REQUIRED:
        st.write(("[ ] " if f in gaps else "[x] ") + f.replace("_", " "))
    if S.stage == "interview" and not gaps:
        if st.button("That is enough, show me the summary"):
            S.stage = "readback"
            say("Here is what I have. Please check it and tell me if anything is wrong.")
            st.rerun()

for t in S.turns:
    with st.chat_message("assistant" if t["speaker"] == "assistant" else "user"):
        st.write(t["content"])

if S.stage == "readback":
    st.info(readback(S.draft))
    if can_confirm(S.draft):
        if st.button("Yes, that is right"):
            save_draft("CONFIRMED")
            S.stage = "done"
            st.rerun()
    else:
        st.warning("A few answers are still missing: " + ", ".join(missing_fields(S.draft)))

if S.stage == "done":
    st.success("Thank you. Your definition is saved and an engineer will take it from here.")
else:
    label = "What should change?" if S.stage == "readback" else "Your answer"
    reply = st.chat_input(label)
    if reply:
        handle_user(reply)
        st.rerun()
