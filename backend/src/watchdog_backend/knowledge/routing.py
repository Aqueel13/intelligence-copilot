"""Which model tier should answer a policy question?

A short factual lookup answered by one or two documents ("Who approves a claim of ₹3,00,000?")
goes to the light model; questions that ask for reasoning, comparison or several things at
once, or whose sources span several documents, go to the standard model. Deliberately simple
and explainable: the reason is shown with the answer and recorded.
"""

import re

from watchdog_backend.knowledge.retrieval import RetrievedChunk

MAX_SIMPLE_WORDS = 18
_REASONING = re.compile(
    r"\b(why|how come|compare|comparison|versus|vs\.?|difference|differ|explain|implications?"
    r"|trade-?offs?|should we|what if|pros|cons|summari[sz]e|list all|all the)\b",
    re.IGNORECASE,
)


def classify(question: str, chunks: list[RetrievedChunk]) -> tuple[str, str]:
    """('simple' | 'complex', reason)."""
    words = len(question.split())
    if words > MAX_SIMPLE_WORDS:
        return "complex", f"long question ({words} words)"
    if question.count("?") > 1:
        return "complex", "several questions in one"
    if m := _REASONING.search(question):
        return "complex", f"asks for reasoning ('{m.group(0).lower()}')"
    docs = {c.doc_key for c in chunks[:3]}
    if len(docs) > 2:
        return "complex", f"top sources span {len(docs)} documents"
    return "simple", "short factual lookup in one or two documents"
