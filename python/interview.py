"""Layer 1 interview logic (docs/layer1-slice-plan.md). Pure functions with no Snowflake dependency, so
they are unit tested offline and imported by the Streamlit app. The interview collects meaning only:
nothing here knows a table or column name, except the denylist the engineer supplies for the output check."""
import json
import re

REQUIRED = ["term", "owner", "said_by", "definition", "counted_per", "questions"]
OPTIONAL = ["excludes", "synonyms", "broken_down_by", "systems_mentioned", "why_it_matters"]
LIST_FIELDS = {"excludes", "synonyms", "broken_down_by", "questions"}
MIN_QUESTIONS = 2

PROMPTS = {
    "term": "What is the business term you want to define, in the words your team uses?",
    "owner": "Which team owns this term?",
    "said_by": "What is your role?",
    "definition": "In your own words, when does something count as this term? Include any time period.",
    "counted_per": "What is one of them, exactly? One customer, one order, one member?",
    "questions": "What questions do people ask that depend on this term? Give me a few, as you would ask them.",
    "excludes": "Is anything deliberately left out, such as internal accounts or test records?",
    "synonyms": "Do people use other names for the same thing?",
    "broken_down_by": "How do people usually split or group it, such as by channel, region or month?",
    "systems_mentioned": "Where do you look when you need this number, and how fresh is it?",
    "why_it_matters": "Why does this definition matter to you? What goes wrong when it is unclear?",
}

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "term": {"type": "string"}, "owner": {"type": "string"}, "said_by": {"type": "string"},
        "definition": {"type": "string"}, "counted_per": {"type": "string"},
        "systems_mentioned": {"type": "string"}, "why_it_matters": {"type": "string"},
        "excludes": {"type": "array", "items": {"type": "string"}},
        "synonyms": {"type": "array", "items": {"type": "string"}},
        "broken_down_by": {"type": "array", "items": {"type": "string"}},
        "questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [],
}

# An identifier that no business user would say: SCHEMA.TABLE, or UPPER_SNAKE_CASE.
IDENTIFIER_SHAPES = [re.compile(r"\b[A-Z][A-Z0-9]{1,9}\.[A-Z][A-Z0-9_]{1,}\b"),
                     re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")]


def _empty(value):
    return value is None or value == "" or value == [] or (isinstance(value, str) and not value.strip())


def new_draft():
    return {}


def missing_fields(draft):
    """Required fields still missing. Questions need at least MIN_QUESTIONS."""
    out = []
    for f in REQUIRED:
        v = draft.get(f)
        if f == "questions":
            if not isinstance(v, list) or len([q for q in v if str(q).strip()]) < MIN_QUESTIONS:
                out.append(f)
        elif _empty(v):
            out.append(f)
    return out


def next_focus(draft, asked_optional=()):
    """The checklist, not the model, decides what is asked next: required fields first, then each
    optional field once."""
    missing = missing_fields(draft)
    if missing:
        return missing[0]
    for f in OPTIONAL:
        if _empty(draft.get(f)) and f not in asked_optional:
            return f
    return None


def is_complete(draft, asked_optional=()):
    return next_focus(draft, asked_optional) is None


def can_confirm(draft):
    return not missing_fields(draft)


def merge_extraction(draft, extracted):
    """Non-empty extracted values replace the draft's; empty ones never erase what the user already said."""
    out = dict(draft)
    for f in REQUIRED + OPTIONAL:
        v = (extracted or {}).get(f)
        if _empty(v):
            continue
        if f in LIST_FIELDS:
            v = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
            if not v:
                continue
        elif isinstance(v, str):
            v = " ".join(v.split())
        out[f] = v
    return out


def build_system_prompt(draft, focus):
    known = {k: v for k, v in draft.items() if not _empty(v)}
    return (
        "You are interviewing a business person to capture what one business term means to them. "
        "Rules: use only plain business language. Never mention tables, columns, databases, schemas, SQL "
        "or system field names, and if the person uses one, ask them to describe it in business words "
        "instead. Ask exactly one short question at a time. Do not suggest answers or fill gaps with "
        "guesses. Do not lecture. If their answer is vague, ask for one concrete example.\n\n"
        f"What you have so far (JSON): {json.dumps(known, ensure_ascii=False)}\n"
        f"The next thing to find out is: {focus} ({PROMPTS.get(focus, focus)})\n"
        "Reply with only your next question."
    )


def build_extraction_prompt(turns):
    convo = "\n".join(f"{t['speaker'].upper()}: {t['content']}" for t in turns)
    return (
        "Read this interview and extract what the BUSINESS PERSON said into the fields below. Use only "
        "what they said, in their words. Leave a field out if they did not say it. Do not invent. "
        "Questions are questions the person would ask of the data.\n\n"
        f"INTERVIEW\n{convo}\n"
    )


def find_schema_words(text, denylist=()):
    """Identifiers found in text: anything on the engineer's denylist, or shaped like SCHEMA.TABLE or
    UPPER_SNAKE_CASE. An empty list means the text is safe to show a business user."""
    hits = []
    for name in denylist:
        if name and re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
            hits.append(name)
    for rx in IDENTIFIER_SHAPES:
        hits.extend(m.group(0) for m in rx.finditer(text))
    seen, out = set(), []
    for h in hits:
        if h.upper() not in seen:
            seen.add(h.upper())
            out.append(h)
    return out


def readback(draft):
    """The draft as plain sentences for the user to confirm or correct."""
    d = draft
    lines = []
    if d.get("term"):
        lines.append(f"The term is \"{d['term']}\", owned by {d.get('owner', 'your team')}.")
    if d.get("definition"):
        lines.append(f"You said it means: {d['definition'].rstrip('.')}.")
    if d.get("counted_per"):
        lines.append(f"It is counted per: {d['counted_per'].rstrip('.')}.")
    for label, key in (("Left out", "excludes"), ("Also called", "synonyms"), ("Usually split by", "broken_down_by")):
        if d.get(key):
            lines.append(f"{label}: {', '.join(d[key])}.")
    if d.get("systems_mentioned"):
        lines.append(f"Where you look: {d['systems_mentioned'].rstrip('.')}.")
    if d.get("why_it_matters"):
        lines.append(f"Why it matters: {d['why_it_matters'].rstrip('.')}.")
    if d.get("questions"):
        lines.append("Questions people ask:")
        lines.extend(f"  - {q}" for q in d["questions"])
    return "\n".join(lines)


def to_glossary_term(draft, term_id):
    """A confirmed draft as a glossary entry in the same shape as glossary/terms.yaml."""
    missing = missing_fields(draft)
    if missing:
        raise ValueError(f"Cannot promote: missing {', '.join(missing)}")
    entry = {"id": term_id}
    for f in ["term", "owner", "said_by", "definition", "excludes", "synonyms", "counted_per",
              "broken_down_by", "systems_mentioned", "why_it_matters", "questions"]:
        if not _empty(draft.get(f)):
            entry[f] = draft[f]
    leaks = find_schema_words(json.dumps(entry, ensure_ascii=False))
    if leaks:
        raise ValueError(f"Cannot promote: schema-like words in the entry: {', '.join(leaks)}")
    return entry
