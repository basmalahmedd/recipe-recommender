#!/usr/bin/env python3
import argparse, json, sys, ast
from pathlib import Path
import pandas as pd

# allow "from app import utils"
sys.path.append(str(Path(__file__).resolve().parents[1]))
from app import utils  # noqa: E402


def parse_ingredients_field(v):
    """
    Accepts raw CSV 'Ingredients' that may be:
      - a list (['egg','milk'])
      - a JSON/Python list string ("['egg','milk']" or '["egg","milk"]')
      - a plain string like "egg, milk; sugar"
    Returns a de-duplicated list[str] of normalized tokens.
    """
    items = []
    if isinstance(v, list):
        items = v
    elif isinstance(v, str):
        s = v.strip()
        if s.startswith("[") and s.endswith("]"):
            # stringified list
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    items = [str(x) for x in parsed]
                else:
                    items = [s]
            except Exception:
                items = [s]
        else:
            items = [s]
    else:
        # NaN / None / other -> no ingredients
        items = []

    # normalize each item and dedupe (order-preserving)
    toks = []
    for it in items:
        toks.extend(utils.split_normalize_ingredients(str(it)))

    seen, out = set(), []
    for t in toks:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main():
    ap = argparse.ArgumentParser(description="Clean raw recipes CSV -> Parquet")
    ap.add_argument("--in", dest="in_path", required=True, help="input CSV path")
    ap.add_argument("--out", dest="out_path", default="data/processed/recipes.parquet", help="output Parquet path")
    args = ap.parse_args()

    in_path = Path(args.in_path)
    out_path = Path(args.out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Load CSV (ignore extra cols like Image_Name / Cleaned_Ingredients)
    df_raw = pd.read_csv(in_path, dtype="object")
    cols = {c.lower(): c for c in df_raw.columns}

    # ---- ID handling: prefer 'id', then 'unnamed: 0', else generate ----
    if "id" in cols:
        id_col = df_raw[cols["id"]]
    elif "unnamed: 0" in cols:
        id_col = df_raw[cols["unnamed: 0"]]
    else:
        id_col = pd.Series(range(len(df_raw)), name="id")

    # Coerce to int64; if any NA, backfill with the row index
    id_series = pd.to_numeric(id_col, errors="coerce")
    if id_series.isna().any():
        id_series = id_series.fillna(pd.Series(range(len(df_raw)), index=df_raw.index))
    id_series = id_series.astype("int64")

    # ---- Required text columns ----
    need = ["title", "ingredients", "instructions"]
    missing = [n for n in need if n not in cols]
    if missing:
        raise SystemExit(f"Missing required column(s): {missing}. Present: {list(df_raw.columns)}")

    # Build normalized dataframe
    df = pd.DataFrame(
        {
            "id": id_series,
            "title": df_raw[cols["title"]].astype(str).apply(utils.normalize_title),
            "ingredients": df_raw[cols["ingredients"]].apply(parse_ingredients_field),
            "instructions": df_raw[cols["instructions"]].astype(str).str.strip(),
        }
    )

    # Filter: need at least 2 ingredients and non-empty instructions
    before = len(df)
    df = df[(df["ingredients"].str.len() >= 2) & (df["instructions"].str.len() > 0)].reset_index(drop=True)

    # Derived fields
    df["ingredients_text"] = df["ingredients"].apply(lambda lst: ",".join(lst))
    df["search_text"] = df["title"] + " " + df["ingredients_text"] + " " + df["instructions"].str.slice(0, 1000)

    # Persist
    df.to_parquet(out_path, index=False)

    # Report
    stats = {
        "rows_in": int(len(df_raw)),
        "rows_out": int(len(df)),
        "dropped": int(before - len(df)),
        "avg_ingredients": float(df["ingredients"].str.len().mean() if len(df) else 0.0),
    }
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
