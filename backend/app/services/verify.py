"""
Verification pipeline (the "hallucination guard"):
  1. Decompose enriched notes into atomic claims (one per sentence, cheap split).
  2. Retrieve the top-k most similar transcript segments by embedding cosine
     similarity — this plays the role Qdrant plays in the full design; at
     lecture-note scale (a few thousand segments per video) brute-force numpy
     cosine similarity is fast enough that a dedicated vector DB isn't needed.
  3. Score alignment with an LLM-as-reranker (see llm.score_claim_alignment).
  4. Gate: >0.7 accept, 0.5-0.7 repair, <0.5 reject.
"""
import re
from . import llm


def split_claims(body_md: str) -> list[str]:
    # Sentence-ish split; good enough for claim-level granularity.
    sentences = re.split(r"(?<=[.!?])\s+", body_md.strip())
    return [s.strip() for s in sentences if len(s.strip()) > 8]


def retrieve_top_k(claim_embedding: list[float], segment_pool: list[dict], k: int = 5) -> list[dict]:
    """segment_pool: [{id, text, embedding}]. Returns top-k by cosine similarity."""
    scored = []
    for seg in segment_pool:
        if not seg.get("embedding"):
            continue
        sim = llm.cosine_sim(claim_embedding, seg["embedding"])
        scored.append((sim, seg))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for _, s in scored[:k]]


def verify_section_body(body_md: str, segment_pool: list[dict]) -> dict:
    """Runs the full gate over one note section's body text.
    Returns {verified_body_md, status, log: [...]}."""
    claims = split_claims(body_md)
    if not claims:
        return {"verified_body_md": body_md, "status": "accepted", "log": []}

    claim_embeddings = llm.embed_texts(claims)
    kept_sentences = []
    log = []
    any_repaired = False
    any_rejected = False

    for claim, emb in zip(claims, claim_embeddings):
        top = retrieve_top_k(emb, segment_pool, k=5)
        best_source = " ".join(s["text"] for s in top[:2]) if top else ""
        score = llm.score_claim_alignment(claim, best_source) if best_source else 0.0

        if score > 0.7:
            kept_sentences.append(claim)
            log.append({"claim": claim, "score": score, "action": "accept"})
        elif score >= 0.5:
            repaired = llm.repair_claim(claim, best_source)
            if repaired:
                kept_sentences.append(repaired)
                any_repaired = True
                log.append({"claim": claim, "score": score, "action": "repair", "repaired": repaired})
            else:
                any_rejected = True
                log.append({"claim": claim, "score": score, "action": "reject"})
        else:
            any_rejected = True
            log.append({"claim": claim, "score": score, "action": "reject"})

    status = "accepted"
    if any_rejected:
        status = "repaired" if kept_sentences else "rejected"
    elif any_repaired:
        status = "repaired"

    return {"verified_body_md": " ".join(kept_sentences), "status": status, "log": log}
