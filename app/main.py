from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator
from contextlib import asynccontextmanager
import os
import ast
import logging
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel
from . import utils
from fastapi.middleware.cors import CORSMiddleware

# ----------------- Logging -----------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("recipegen")

# ----------------- Config (env-tunable) -----------------
DATA_PROCESSED = os.getenv("DATA_PROCESSED", "data/processed/recipes.parquet")

TOPK_CAND = int(os.getenv("TOPK_CAND", "50"))
W_TFIDF   = float(os.getenv("W_TFIDF", "0.3"))
W_JACCARD = float(os.getenv("W_JACCARD", "0.7"))
LOW_CONF  = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.2"))

# Cap for response size to protect CPU/time
K_MAX = int(os.getenv("K_MAX", "10"))  

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

# CORS (comma-separated list or "*")
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "*").split(",") if o]  

REQUIRED_COLS = ("id", "title", "ingredients", "instructions")

# ----------------- I/O models -----------------
class RecommendIn(BaseModel):
    ingredients: list[str]
    k: int = 1

    @field_validator("ingredients")
    @classmethod  # ensure non-empty list post-normalization
    def _non_empty(cls, v):
        if not isinstance(v, list):
            raise ValueError("ingredients must be a list of strings")
        return v

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
    df: pd.DataFrame | None = None
    vec: TfidfVectorizer | None = None
    tfidf = None
    ready: bool = False

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

def _ensure_search_text(df: pd.DataFrame) -> pd.Series:  
    """
    Use existing 'search_text' if present; otherwise build a simple one
    from title + normalized ingredients + instructions.
    """
    if "search_text" in df.columns:
        return df["search_text"].fillna("")
    log.warning("'search_text' column missing; constructing fallback.")
    titles = df["title"].fillna("").astype(str)
    # ingredients -> normalized tokens joined by space
    ings = df["ingredients"].apply(lambda x: " ".join(_coerce_ingredients(x)) if pd.notna(x) else "")
    instr = df["instructions"].fillna("").astype(str)
    return (titles + " " + ings + " " + instr).str.lower()

# ----------------- Lifespan -----------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if not os.path.exists(DATA_PROCESSED):
            raise FileNotFoundError(f"Processed parquet not found at {DATA_PROCESSED}. "
                                    f"Run ETL to create it.")

        # Parquet support requires pyarrow or fastparquet; prefer pyarrow
        try:
            import pyarrow  # noqa: F401
        except Exception as e:
            raise RuntimeError("Missing dependency 'pyarrow' for reading parquet. "
                               "Add 'pyarrow' to requirements.txt.") from e

        df = pd.read_parquet(DATA_PROCESSED)
        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"Parquet missing required columns: {missing}. "
                             f"Expected columns include: {REQUIRED_COLS}")

        texts = _ensure_search_text(df).tolist()

        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, max_df=0.8)
        tfidf = vec.fit_transform(texts)

        state.df = df
        state.vec = vec
        state.tfidf = tfidf
        state.ready = True

        log.info("Startup complete: rows=%d, vocab_size=%d, tfidf_shape=%s",
                 len(df),
                 len(vec.vocabulary_) if vec.vocabulary_ else 0,
                 getattr(tfidf, "shape", None))
        yield

    except Exception as e:
        # Make it obvious in logs and readiness probe
        log.exception("Startup failed: %s", e)
        state.ready = False
        # Still yield so /health can respond; /ready will report not ready
        yield

app = FastAPI(title="RecipeGen MVP", version="0.0.2", lifespan=lifespan)

# enable CORS so React frontend can call backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
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
    """Liveness: process is up."""
    return {"status": "ok", "ready": bool(state.ready)}

@app.get("/ready")
def ready():
    """Readiness: model/vectorizer loaded and data present."""
    return {
        "ready": bool(state.ready and state.df is not None and state.vec is not None and state.tfidf is not None),
        "rows": int(len(state.df)) if state.df is not None else 0
    }

@app.post("/recommend", response_model=RecommendOut)
def recommend(req: RecommendIn):
    if not state.ready or state.df is None or state.vec is None or state.tfidf is None:
        raise HTTPException(status_code=503, detail="Service not ready. Try again soon.")

    # Normalize & dedupe input tokens
    _seen = set()
    q_tokens = []
    for x in req.ingredients:
        tok = utils.normalize_ingredient(x)
        if not tok or tok in _seen:
            continue
        _seen.add(tok)
        q_tokens.append(tok)

    if not q_tokens:
        raise HTTPException(status_code=400, detail="Provide at least one valid ingredient.")

    # Cap k to protect CPU/runtime
    k_req = int(req.k) if isinstance(req.k, int) else 1
    k_req = max(1, min(k_req, K_MAX))

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

    # Sort by score (you can swap to key=lambda t: (t[2], t[1]) to prioritize coverage)
    scored.sort(key=lambda t: t[1], reverse=True)

    k = max(1, min(k_req, len(scored)))
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
