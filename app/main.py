from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from contextlib import asynccontextmanager
import os, ast
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from . import utils
from fastapi.middleware.cors import CORSMiddleware  

# ----------------- Config (env-tunable) -----------------
DATA_PROCESSED = os.getenv("DATA_PROCESSED", "data/processed/recipes.parquet")

TOPK_CAND = int(os.getenv("TOPK_CAND", "50"))
W_TFIDF   = float(os.getenv("W_TFIDF", "0.3"))
W_JACCARD = float(os.getenv("W_JACCARD", "0.7"))
LOW_CONF  = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.2"))

# Pantry tokens to ignore in overlap/Jaccard (can override via env)
PANTRY = set(
    os.getenv(
        "PANTRY",
        "salt,kosher_salt,coarse_kosher_salt,pepper,black_pepper,water,oil,olive_oil,vegetable_oil,sugar,sea_salt,canola_oil"
    ).replace(" ", "").split(",")
)

# Require some overlap; penalize weak matches
MIN_OVERLAP = int(os.getenv("MIN_OVERLAP", "2"))
PENALTY_LOW_OVERLAP = float(os.getenv("PENALTY_LOW_OVERLAP", "0.6"))

# When to flag low confidence based on coverage of non-pantry query ingredients
COVERAGE_LOW = float(os.getenv("COVERAGE_LOW", "0.5"))

# ----------------- I/O models -----------------
class RecommendIn(BaseModel):
    ingredients: list[str]
    k: int = 1

class RecipeOut(BaseModel):
    id: int
    title: str
    ingredients: list[str]
    instructions: str
    score: float
    matched: list[str]
    missing: list[str]
    coverage: float  # 0..1 (non-pantry matches / non-pantry query size)

class RecommendOut(BaseModel):
    items: list[RecipeOut]
    low_confidence: bool

# ----------------- App state -----------------
class _State:
    df = None
    vec = None
    tfidf = None

state = _State()

# ----------------- Helpers -----------------
def _jaccard(a, b) -> float:
    """Pantry-aware Jaccard similarity."""
    sa = {x for x in a if x and x not in PANTRY}
    sb = {x for x in b if x and x not in PANTRY}
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def _coerce_ingredients(cell) -> list[str]:
    """Return a clean list[str] of NORMALIZED ingredient tokens (matching utils.normalize_ingredient output)."""
    if cell is None:
        return []

    if isinstance(cell, (list, tuple)):
        parts = []
        for it in cell:
            if it is None:
                continue
            parts.extend(utils.split_normalize_ingredients(str(it)))
        seen, out = set(), []
        for p in parts:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    if hasattr(cell, "tolist"):
        try:
            return _coerce_ingredients(cell.tolist())
        except Exception:
            pass

    if isinstance(cell, str):
        s = cell.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple)):
                    return _coerce_ingredients(parsed)
            except Exception:
                pass
        parts = utils.split_normalize_ingredients(s)
        seen, out = set(), []
        for p in parts:
            if p and p not in seen:
                seen.add(p)
                out.append(p)
        return out

    return []

# ----------------- Lifespan -----------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    state.df = pd.read_parquet(DATA_PROCESSED)
    texts = state.df["search_text"].fillna("").tolist()
    state.vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_df=0.8)
    state.tfidf = state.vec.fit_transform(texts)
    yield

app = FastAPI(title="RecipeGen MVP", version="0.0.1", lifespan=lifespan)

# enable CORS so React frontend can call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or ["http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- Routes -----------------
@app.get("/")
def redirect_to_docs():
    """Redirect root URL to /docs automatically."""
    return RedirectResponse(url="/docs")

@app.get("/health")
def health():
    return {"status": "ok", "rows": int(len(state.df)) if state.df is not None else 0}

@app.post("/recommend", response_model=RecommendOut)
def recommend(req: RecommendIn):
    _seen = set()
    q_tokens = []
    for x in req.ingredients:
        tok = utils.normalize_ingredient(x)
        if not tok or tok in _seen:
            continue
        _seen.add(tok)
        q_tokens.append(tok)
    q_text = " ".join(q_tokens)

    qv = state.vec.transform([q_text])
    sims = linear_kernel(qv, state.tfidf).ravel()
    n = int(sims.shape[0])
    k_cand = max(1, min(TOPK_CAND, n))
    order = np.argsort(-sims)
    top = order[:k_cand]

    scored: list[tuple[int, float, float]] = []
    for idx in top:
        ing_list = _coerce_ingredients(state.df.iloc[idx]["ingredients"])
        j = _jaccard(q_tokens, ing_list)
        score = W_TFIDF * float(sims[idx]) + W_JACCARD * j

        qa = {t for t in q_tokens if t not in PANTRY}
        da = {t for t in ing_list if t not in PANTRY}
        overlap = len(qa & da)
        if overlap < MIN_OVERLAP:
            score *= PENALTY_LOW_OVERLAP

        coverage = (overlap / max(1, len(qa))) if qa else 0.0
        scored.append((int(idx), float(score), float(coverage)))

    scored.sort(key=lambda t: t[1], reverse=True)

    k = max(1, min(req.k, len(scored)))
    items: list[RecipeOut] = []
    for idx, sc, cov in scored[:k]:
        row = state.df.iloc[idx]
        ing_list = _coerce_ingredients(row["ingredients"])

        qa = {t for t in q_tokens if t not in PANTRY}
        da = {t for t in ing_list if t not in PANTRY}
        matched = sorted(qa & da)
        missing = sorted(qa - da)

        coverage = 1.0 if not qa else (len(qa & da) / len(qa))

        items.append(
            RecipeOut(
                id=int(row["id"]) if pd.notna(row["id"]) else 0,
                title=str(row["title"]),
                ingredients=ing_list,
                instructions=str(row["instructions"]),
                score=float(sc),
                matched=matched,
                missing=missing,
                coverage=float(coverage),
            )
        )

    low_conf = (len(scored) == 0) or (items and items[0].coverage < COVERAGE_LOW)
    return RecommendOut(items=items, low_confidence=low_conf)
