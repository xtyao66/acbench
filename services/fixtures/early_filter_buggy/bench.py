"""Performance driver: exercise the hot path at a scale where the algorithmic
cost dominates measurement noise. Prints one JSON line: elapsed_s + workload."""
import json, sys, time
sys.path.insert(0, "src")
from early_filter.ranker import rank_top_k

# Build a batch of candidate documents. Only candidates that are active, in the
# requested locale, and not blocked are eligible -- roughly one in two here.
# Every document carries a non-trivial token body (DOC_TERMS tokens) so the
# relevance score is real per-candidate CPU work. N and the document/query sizes
# are chosen so the buggy baseline runs comfortably in the ~0.5-2s range where
# the algorithmic cost dominates measurement noise.
N = 100000
LOCALE = "en-US"
DOC_TERMS = 160
QUERY_TERMS = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel")
VOCAB = [f"w{i}" for i in range(40)]

candidates = []
for i in range(N):
    # ~1/2 of candidates are eligible (active AND right locale AND not blocked),
    # so early filtering avoids scoring the other half.
    active = (i % 2 == 0)
    locale = LOCALE if (i % 2 == 0) else "fr-FR"
    body = [VOCAB[(i + j) % len(VOCAB)] for j in range(DOC_TERMS)]
    # Sprinkle some query terms in so scores vary.
    if i % 4 == 0:
        body[0] = "alpha"
    if i % 5 == 0:
        body[1] = "bravo"
    candidates.append({
        "doc_id": f"doc-{i:06d}",
        "tokens": body,
        "active": active,
        "locale": locale,
    })

blocked = {f"doc-{i:06d}" for i in range(0, N, 30)}

t = time.perf_counter()
out = rank_top_k(candidates, QUERY_TERMS, LOCALE, blocked, top_k=10)
dt = time.perf_counter() - t
print(json.dumps({"elapsed_s": dt, "n": N, "returned": len(out)}))
