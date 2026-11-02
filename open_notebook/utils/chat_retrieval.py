"""Query-scoped original-text evidence for notebook context that cannot fit whole."""

import re

from open_notebook.database.repository import ensure_record_id, repo_query
from open_notebook.utils.embedding import generate_embedding

MAX_CONTEXT_CHARS = 100_000
STOP = {
    "what",
    "which",
    "does",
    "this",
    "that",
    "with",
    "from",
    "have",
    "many",
    "book",
    "document",
    "about",
    "please",
    "there",
    "they",
    "were",
    "when",
    "where",
}


def lexical_passages(text, query, budget):
    terms = {
        word.rstrip("s")
        for word in re.findall(r"\w+", query.lower())
        if len(word) > 2 and word not in STOP
    }
    windows = [(i, text[i : i + 4000]) for i in range(0, len(text), 3500)]
    ranked = sorted(
        windows,
        key=lambda item: (
            -sum(
                min(
                    len(re.findall(r"\b" + re.escape(term) + r"s?\b", item[1].lower())),
                    5,
                )
                for term in terms
            ),
            item[0],
        ),
    )
    selected = [(0, text[:4000])]
    used = len(selected[0][1])
    for offset, passage in ranked:
        if offset == 0 or used + len(passage) > budget:
            continue
        selected.append((offset, passage))
        used += len(passage)
        if used >= budget - 4000:
            break
    return "\n\n".join(
        f"[Original-text excerpt, character offset {offset}]\n{passage}"
        for offset, passage in sorted(selected)
    )


async def retrieve_notebook_context(context, query):
    if not isinstance(context, dict) or len(str(context)) <= MAX_CONTEXT_CHARS:
        return context
    sources = context.get("sources", [])
    result = {
        "sources": [],
        "notes": [],
        "retrieval_notice": "Selected original-text excerpts for this question, not the complete documents. Do not infer exhaustive totals or absence from retrieval alone. Cite the supplied source IDs. Generated insights are secondary; verify claims against original excerpts.",
    }
    # A shared budget also prevents many individually small sources overflowing.
    remaining = MAX_CONTEXT_CHARS - 10000
    embed = None
    eligible = [s for s in sources if isinstance(s, dict)]
    for index, source in enumerate(eligible):
        share = max(0, remaining // max(1, len(eligible) - index))
        if share < 2000:
            break
        text = source.get("full_text") or ""
        item = {k: v for k, v in source.items() if k not in ("full_text", "insights")}
        # Explicit insights-only choices remain insights-only.
        insight_text = str(source.get("insights", []))
        item["insights"] = insight_text[: min(6000, share // 4)]
        budget = max(0, share - len(str(item)) - 1000)
        if text and budget:
            excerpts = ""
            if len(text) > budget and source.get("id"):
                try:
                    if embed is None:
                        embed = await generate_embedding(query)
                    rows = await repo_query(
                        "SELECT content, `order`, vector::similarity::cosine(embedding, $embed) AS score FROM source_embedding WHERE source = $source ORDER BY score DESC LIMIT 16",
                        {"embed": embed, "source": ensure_record_id(str(source["id"]))},
                    )
                    excerpts = "\n\n".join(
                        f"[Indexed original-text passage, chunk {r['order']}]\n{r['content']}"
                        for r in rows
                    )
                except Exception as exc:
                    from loguru import logger

                    logger.warning(
                        "Vector retrieval unavailable: {}", type(exc).__name__
                    )
                excerpts = excerpts[: budget // 2]
            item["full_text"] = (
                text
                if len(text) <= budget
                else lexical_passages(text, query, max(0, budget - len(excerpts)))
                + "\n\n"
                + excerpts
            )
        remaining -= len(str(item))
        result["sources"].append(item)
    for note in context.get("notes", []):
        if remaining <= 0:
            break
        # Preserve source IDs while bounding note text too.
        item = dict(note) if isinstance(note, dict) else {"content": str(note)}
        for key in ("content", "full_text"):
            if isinstance(item.get(key), str):
                item[key] = item[key][: max(0, remaining - 1000)]
        remaining -= len(str(item))
        result["notes"].append(item)
    return result
