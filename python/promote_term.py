"""PROMOTE_TERM: copies one confirmed interview draft into GLOSSARY, so MAP_TERM can map it.

Layer 1, task 4 (docs/layer1-slice-plan.md). Runs as SVC_MAPPER, which can read the interview drafts
but never write them: the promotion is recorded in the mapper's own PROMOTIONS table instead.
"""


def main(session, draft_id, term_id, app_db="SVC_APP"):
    require_mapper_role(session)
    db = check_ident(app_db)
    term_id = check_ident(term_id)
    app = f"{db}.MAPPER"

    rows = session.sql(f"SELECT STATUS, TERM FROM {db}.INTERVIEW.TERM_DRAFTS WHERE DRAFT_ID = ?",
                       params=[draft_id]).collect()
    if not rows:
        raise ValueError(f"No interview draft {draft_id!r}")
    status, term = rows[0][0], rows[0][1]
    if status != "CONFIRMED":
        raise ValueError(f"Draft {draft_id} is {status}: only a draft the business user confirmed can be promoted")
    draft = json.loads(term) if isinstance(term, str) else term

    if session.sql(f"SELECT 1 FROM {app}.GLOSSARY WHERE TERM_ID = ?", params=[term_id]).collect():
        raise ValueError(f"Glossary term {term_id} already exists; promote under a new TERM_ID")

    # Completeness and the built-in identifier shapes are checked here.
    entry = to_glossary_term(draft, term_id)
    # Then every table and column name the mapper has profiled. The id is ours, so it is left out.
    denylist = [r[0] for r in session.sql(
        f"SELECT DISTINCT NAME FROM (SELECT TABLE_NAME AS NAME FROM {app}.COLUMN_PROFILE "
        f"UNION SELECT COLUMN_NAME FROM {app}.COLUMN_PROFILE) WHERE LENGTH(NAME) >= 4").collect()]
    leaks = find_schema_words(json.dumps({k: v for k, v in entry.items() if k != "id"}, ensure_ascii=False), denylist)
    if leaks:
        raise ValueError(f"Cannot promote: catalog names in the entry: {', '.join(leaks)}")

    body = json.dumps(entry, ensure_ascii=False)
    session.sql(f"INSERT INTO {app}.GLOSSARY SELECT ?, PARSE_JSON(?), CURRENT_TIMESTAMP()",
                params=[term_id, body]).collect()
    session.sql(f"INSERT INTO {app}.PROMOTIONS SELECT ?, ?, CURRENT_TIMESTAMP()",
                params=[draft_id, term_id]).collect()
    return {"term_id": term_id, "draft_id": draft_id, "term": entry.get("term"), "fields": sorted(entry)}
