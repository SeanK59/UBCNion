"""
Generate cod_lookup.json from the COD public MySQL server.
The output is a compact JSON object keyed by Hill-notation formula (no spaces),
where each value is a list of up to MAX_PER_KEY structure entries.

Run once:
    python generate_cod_lookup.py

Requires: pip install pymysql
"""

import re
import json
from collections import defaultdict
import pymysql

ORGANIC_ONLY_ELS = {'H', 'B', 'C', 'N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I'}

# ---------------------------------------------------------------------------
# Formula helpers
# ---------------------------------------------------------------------------

def parse_cod_formula(formula_str):
    """Parse COD formula string like 'Ca Ti O3' or 'La1.85 Sr0.15 Cu O4'."""
    counts = {}
    for token in formula_str.strip().split():
        m = re.match(r'^([A-Z][a-z]?)(\d*\.?\d*)$', token)
        if m:
            el = m.group(1)
            n = float(m.group(2)) if m.group(2) else 1.0
            counts[el] = counts.get(el, 0) + n
    return counts


def make_key(counts):
    """Return Hill-ordered key string, e.g. 'O3SrTi' or 'CaO3Ti'."""
    els = list(counts.keys())
    if 'C' in els:
        rest = sorted(e for e in els if e not in ('C', 'H'))
        ordered = ['C'] + (['H'] if 'H' in els else []) + rest
    else:
        ordered = sorted(els)

    parts = []
    for el in ordered:
        n = counts[el]
        r = round(n)
        if abs(n - r) < 0.005:          # effectively integer
            parts.append(el if r == 1 else f'{el}{r}')
        else:
            # keep 2-decimal precision for non-stoichiometric, strip trailing zeros
            s = f'{n:.2f}'.rstrip('0').rstrip('.')
            parts.append(f'{el}{s}')
    return ''.join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

print("Connecting to COD MySQL at sql.crystallography.net …")
conn = pymysql.connect(
    host='sql.crystallography.net',
    user='cod_reader',
    password='',
    db='cod',
    charset='utf8',
    connect_timeout=30,
    read_timeout=300,
)

cur = conn.cursor()

# Fetch only non-duplicate, non-error rows with valid cell data.
# 'flags' LIKE '%has coordinates%' keeps only experimentally solved structures.
QUERY = """
SELECT formula, vol, Z, sg
FROM data
WHERE vol > 0
  AND Z > 0
  AND vol IS NOT NULL
  AND Z IS NOT NULL
  AND formula IS NOT NULL
  AND (duplicateof IS NULL OR duplicateof = '')
  AND (status IS NULL OR status = '')
"""

print("Querying … (this may take a minute)")
cur.execute(QUERY)
rows = cur.fetchall()
conn.close()
print(f"Fetched {len(rows):,} rows from COD.")

lookup = defaultdict(dict)  # key -> {sg -> entry}
skipped = 0

for formula, vol, Z, sg in rows:
    if not formula:
        continue
    try:
        counts = parse_cod_formula(formula)
        if not counts:
            continue
        # Skip purely organic/molecular entries — not relevant for TEM.
        # Exception: pure carbon allotropes (diamond, graphite, fullerenes…) are kept.
        els = set(counts.keys())
        if els.issubset(ORGANIC_ONLY_ELS) and els != {'C'}:
            continue
        key = make_key(counts)
        sg_key = (sg or '').strip() or '_'
        # Keep one entry per space group (first encountered)
        if sg_key not in lookup[key]:
            entry = {'v': round(float(vol), 2), 'Z': int(Z)}
            if sg and sg.strip():
                entry['s'] = sg.strip()
            lookup[key][sg_key] = entry
    except Exception:
        skipped += 1

# Convert to lists
lookup_out = {k: list(v.values()) for k, v in lookup.items()}

print(f"Unique formula keys : {len(lookup_out):,}")
print(f"Skipped (parse err) : {skipped:,}")

out_path = 'cod_lookup.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(lookup_out, f, separators=(',', ':'), ensure_ascii=False)

size_mb = __import__('os').path.getsize(out_path) / 1e6
print(f"Written to {out_path}  ({size_mb:.1f} MB)")
