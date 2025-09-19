import re
from typing import List

_RX_WS      = re.compile(r"\s+")
_RX_QTY     = re.compile(r"\b\d+(?:[./]\d+)?(?:\s*-\s*\d+(?:[./]\d+)?)?\b")
_RX_UFRACT  = re.compile(r"[¼½¾⅓⅔⅛⅜⅝⅞]")
_RX_UNITS = re.compile(
    r"\b("
    r"tsp|tsps|teaspoon|teaspoons|tbsp|tbsps|tablespoon|tablespoons|"
    r"cup|cups|oz|ounce|ounces|lb|lbs|pound|pounds|"
    r"g|gram|grams|kg|kgs|kilogram|kilograms|"
    r"ml|milliliter|milliliters|l|liter|liters|"
    r"stick|sticks|clove|cloves|rib|ribs|slice|slices|"
    r"pint|pints|quart|quarts|pinch|dash|inch|inches"
    r")\b"
)
_RX_PARENS  = re.compile(r"\([^)]*\)")
_RX_SPLIT   = re.compile(r"\s*(?:,|;|/|&| and )\s*", re.IGNORECASE)
_RX_PUNCT   = re.compile(r"[^\w\s-]")

# Expanded stopwords: prep states, glue words, appliance noise, and leftovers from your top-100
# Expanded stopwords: prep states, glue words, appliance noise, and leftovers from your top-100
STOPWORDS = frozenset({
    # articles / glue
    "a", "an", "the", "or", "and", "of", "at", "into", "for", "such", "such_as", "in", "very",
    # common descriptors / states
    "fresh", "large", "small", "medium", "extra", "extra_virgin", "to", "taste", "optional",
    "chopped", "diced", "minced", "sliced", "ground", "crushed", "grated", "shredded",
    "skinless", "boneless", "divided", "plus", "serving", "slivered",
    "finely", "freshly", "thinly", "coarsely", "roughly", "lightly", "beaten",
    "melted", "softened", "room", "temperature", "room_temperature", "more", "about", "total", "cored",
    "garnish", "twist", "casing_removed", "torn", "cut", "piece", "pieces", "loaf", "stick", "qt",
    # prep tokens that were still frequent
    "halved", "trimmed", "drained", "rinsed", "toasted", "seeded", "lengthwise", "cube", "cubes",
    "thick", "quartered", "crosswise", "pitted", "separated", "scrubbed", "stemmed", "smashed",
    "thawed", "wedge", "white", "split", "patted_dry",
    # peel/stalk/leaf/count words
    "peeled", "sprig", "stalk", "stalks", "leaf", "leaves", "bunch", "handful",
    # appliance-ish noise
    "electric", "pressure", "cooker", "instant", "pot", "nonstick", "spray",
})

def _plural_fold(token: str) -> str:
    # heuristic plural -> singular
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    # common patterns which are safe to trim 'es' (potatoes->potato, heroes->hero)
    if token.endswith("oes") or token.endswith("ses"):
        return token[:-2]
    # drop trailing s but avoid chopping 'ss'
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token

def normalize_title(s: str) -> str:
    s = (s or "").strip()
    s = _RX_WS.sub(" ", s)
    return s[:1].upper() + s[1:].lower() if s else ""

def normalize_ingredient(token: str) -> str:
    t = (token or "").lower()
    t = _RX_PARENS.sub(" ", t)     # remove (optional), (divided), etc.
    t = _RX_UFRACT.sub(" ", t)     # remove unicode fractions
    t = _RX_QTY.sub(" ", t)        # remove numbers and ranges
    t = _RX_UNITS.sub(" ", t)      # remove units (incl. inch/inches)
    t = _RX_PUNCT.sub(" ", t)      # strip punctuation
    t = t.replace("-", " ")
    t = _RX_WS.sub(" ", t).strip()

    parts = [p for p in t.split(" ") if p]
    parts = [p for p in parts if p not in STOPWORDS]
    parts = [_plural_fold(p) for p in parts]

    t = " ".join(parts).strip()
    t = t.replace(" ", "_")

    # ---- canonicalize common patterns from your corpus ----
    # salts/sugars/extracts
    t = re.sub(r"^(coarse_)?kosher_salt$", "kosher_salt", t)
    t = re.sub(r"^(fine_|flaky_)?sea_salt$", "sea_salt", t)
    t = re.sub(r"^(granulated_)?sugar$", "sugar", t)
    t = re.sub(r"^(pure_)?vanilla_extract$", "vanilla_extract", t)

    # herbs/cheeses
    t = re.sub(r"^italian_parsley$", "parsley", t)
    t = re.sub(r"^parmesan_cheese$", "parmesan", t)
    t = re.sub(r"^parmigiano_reggiano$", "parmesan", t)

    # fats/butter
    t = re.sub(r"^chilled_unsalted_butter$", "unsalted_butter", t)

    # citrus/zest/wedges
    t = re.sub(r"^lemon_peel$", "lemon_zest", t)
    t = re.sub(r"^(\w+)_wedge$", r"\1", t)  # lime_wedge -> lime

    # broths/stocks & sodium qualifiers
    t = re.sub(r"^(low_salt|low_sodium|reduced_sodium)_(.+)$", r"\2", t)  # drop qualifier
    t = re.sub(r"_stock$", "_broth", t)                                   # *_stock -> *_broth

    # cooking sprays (drop)
    t = re.sub(r"^nonstick_.*spray$", "", t)

    # single-token leftovers to drop
    t = re.sub(r"^(very|at|white|split|patted_dry)$", "", t)

    # celery parts
    t = re.sub(r"^celery_(stalk|stalks|leaf|leaves)$", "celery", t)

    # parsley variants
    t = re.sub(r"^(sprig_|flat_(leaf_)?)?parsley$", "parsley", t)

    # white_bread tail collapse
    if "white_bread" in t:
        t = "white_bread"

    # any *olive_oil -> olive_oil
    if t.endswith("olive_oil"):
        t = "olive_oil"
        
    # drop 'sprig' prefix/suffix (sprig_thyme -> thyme, thyme_sprig -> thyme)
    t = re.sub(r"^sprig_", "", t)
    t = re.sub(r"_sprig$", "", t)

    # heavy_whipping_cream -> heavy_cream
    t = re.sub(r"^heavy_whipping_cream$", "heavy_cream", t)

    # bay -> bay_leaf
    if t == "bay":
        t = "bay_leaf"

    # dry wine variants
    t = re.sub(r"^dry_white_wine$", "white_wine", t)
    t = re.sub(r"^dry_red_wine$", "red_wine", t)
    t = re.sub(r"^dry_wine$", "white_wine", t)  
    
    # chicken_part / chicken_parts -> chicken  (extra-safe, even if earlier rules miss)
    t = re.sub(r"^(.+)_part(s?)$", r"\1", t)

    return t

def split_normalize_ingredients(s: str) -> List[str]:
    if not s:
        return []
    parts = [p for p in _RX_SPLIT.split(s) if p and p.strip()]
    out = [normalize_ingredient(p) for p in parts]
    # dedupe preserving order
    seen, res = set(), []
    for x in out:
        if x and x not in seen:
            seen.add(x)
            res.append(x)
    return res
