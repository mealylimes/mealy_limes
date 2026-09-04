#!/usr/bin/env python3
"""Generate a static, GitHub Pages-ready HTML site from recipes.db.

Reads the anonymized catalog in recipes.db and writes docs/ containing:
  * one page per recipe (docs/recipes/<slug>-<variant_id>.html)
  * one index page per category (docs/categories/<kind>-<name>.html)
  * a home page (docs/index.html)
  * a .nojekyll marker so GitHub Pages serves the files verbatim

Pure Python 3 standard library. All links are relative so the site works under a
project-pages subpath (https://<user>.github.io/<repo>/). Run: python3 generate_site.py
"""

import html
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).with_name("recipes.db")
OUT = Path(__file__).with_name("docs")

BOOTSTRAP_CSS = (
    '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" '
    'rel="stylesheet" '
    'integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" '
    'crossorigin="anonymous">'
)
BOOTSTRAP_JS = (
    '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" '
    'integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" '
    'crossorigin="anonymous"></script>'
)

# Human labels for the raw category names.
RULESET_LABELS = {
    "dinner": "Dinner",
    "breakfast": "Breakfast",
    "dessert": "Dessert",
    "simple": "Simple & Quick",
    "snack": "Snacks",
    "cpg": "Packaged",
}
FOOD_LABELS = {
    "meat": "Meat",
    "vegetarian": "Vegetarian",
    "fish": "Fish & Seafood",
}
# Key nutrients surfaced as cards, in display order: (db key, label, unit).
KEY_NUTRIENTS = [
    ("energy", "Calories", "kcal"),
    ("protein", "Protein", "g"),
    ("carbs", "Carbs", "g"),
    ("fat", "Fat", "g"),
    ("fiber", "Fiber", "g"),
    ("sodium", "Sodium", "mg"),
]
# Pretty labels for the full nutrient table; anything unlisted is title-cased.
NUTRIENT_LABELS = {
    "b1_thiamine": "Vitamin B1 (Thiamine)",
    "b2_riboflavin": "Vitamin B2 (Riboflavin)",
    "b3_niacin": "Vitamin B3 (Niacin)",
    "b5_pantothenic_acid": "Vitamin B5 (Pantothenic acid)",
    "b6_pyridoxine": "Vitamin B6 (Pyridoxine)",
    "b12_cobalamin": "Vitamin B12 (Cobalamin)",
    "vitamin_a": "Vitamin A",
    "vitamin_c": "Vitamin C",
    "vitamin_d": "Vitamin D",
    "vitamin_e": "Vitamin E",
    "vitamin_k": "Vitamin K",
    "omega_3": "Omega-3",
    "omega_6": "Omega-6",
    "energy": "Energy",
    "carbs": "Carbohydrates",
}
# Units for the full nutrient table (best-effort; unlisted nutrients show grams).
MG_NUTRIENTS = {
    "sodium", "potassium", "calcium", "magnesium", "phosphorus", "cholesterol",
    "choline", "vitamin_c", "vitamin_e", "b1_thiamine", "b2_riboflavin",
    "b3_niacin", "b5_pantothenic_acid", "b6_pyridoxine", "caffeine",
}
UG_NUTRIENTS = {
    "vitamin_a", "vitamin_d", "vitamin_k", "b12_cobalamin", "folate",
    "selenium", "iodine",
}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def rel(from_path: Path, to_path: Path) -> str:
    """Relative URL from one output file to another (POSIX slashes)."""
    return os.path.relpath(to_path, from_path.parent).replace(os.sep, "/")


def nutrient_label(key: str) -> str:
    return NUTRIENT_LABELS.get(key, key.replace("_", " ").title())


def nutrient_unit(key: str) -> str:
    if key == "energy":
        return "kcal"
    if key in MG_NUTRIENTS:
        return "mg"
    if key in UG_NUTRIENTS:
        return "µg"
    return "g"


def fmt_num(value) -> str:
    if value is None:
        return "—"
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def page(title: str, body: str, depth: int) -> str:
    """Wrap body in the shared HTML shell. depth = directory depth below docs/."""
    up = "../" * depth
    home = up + "index.html"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
{BOOTSTRAP_CSS}
</head>
<body class="bg-body-tertiary">
<nav class="navbar navbar-expand-lg bg-dark border-bottom" data-bs-theme="dark">
  <div class="container">
    <a class="navbar-brand fw-bold" href="{esc(home)}">🍋 Mealy Limes Recipes</a>
  </div>
</nav>
<main class="container my-4">
{body}
</main>
{BOOTSTRAP_JS}
</body>
</html>
"""


def load_data(conn):
    conn.row_factory = sqlite3.Row
    recipes = {r["variant_id"]: dict(r) for r in conn.execute("SELECT * FROM recipe")}

    instructions = defaultdict(list)
    for r in conn.execute(
        "SELECT variant_id, primary_message, secondary_message "
        "FROM instruction ORDER BY variant_id, position"
    ):
        instructions[r["variant_id"]].append((r["primary_message"], r["secondary_message"]))

    line_items = defaultdict(list)
    for r in conn.execute(
        "SELECT variant_id, quantity, ingredient_name FROM line_item ORDER BY variant_id, id"
    ):
        line_items[r["variant_id"]].append((r["quantity"], r["ingredient_name"]))

    cookware = defaultdict(list)
    for r in conn.execute(
        "SELECT rc.variant_id, c.name FROM recipe_cookware rc "
        "JOIN cookware c ON c.id = rc.cookware_id ORDER BY rc.variant_id, c.name"
    ):
        cookware[r["variant_id"]].append(r["name"])

    nutrition = defaultdict(dict)
    for r in conn.execute("SELECT variant_id, nutrient, value FROM nutrition"):
        nutrition[r["variant_id"]][r["nutrient"]] = r["value"]

    # category rows + membership (all rows are item_type='catalog')
    categories = {c["id"]: dict(c) for c in conn.execute("SELECT * FROM category")}
    cat_members = defaultdict(list)   # category_id -> [variant_id]
    recipe_cats = defaultdict(list)   # variant_id -> [category_id]
    for r in conn.execute(
        "SELECT category_id, item_id FROM recipe_category WHERE item_type='catalog'"
    ):
        vid = int(r["item_id"])
        if vid in recipes:
            cat_members[r["category_id"]].append(vid)
            recipe_cats[vid].append(r["category_id"])

    return recipes, instructions, line_items, cookware, nutrition, categories, cat_members, recipe_cats


def cat_slug(cat) -> str:
    prefix = "ruleset" if cat["kind"] == "ruleset" else "food"
    return f"{prefix}-{cat['name']}"


def cat_label(cat) -> str:
    if cat["kind"] == "ruleset":
        return RULESET_LABELS.get(cat["name"], cat["name"].title())
    return FOOD_LABELS.get(cat["name"], cat["name"].title())


def recipe_path(recipe) -> Path:
    return OUT / "recipes" / f"{recipe['slug']}-{recipe['variant_id']}.html"


def cat_path(cat) -> Path:
    return OUT / "categories" / f"{cat_slug(cat)}.html"


def meta_badges(recipe) -> str:
    bits = []
    ct = recipe["cooking_minutes"]
    if ct:
        bits.append(f'<span class="badge text-bg-light border">⏱ {esc(ct)} min</span>')
    sc = recipe["serving_count"]
    if sc:
        bits.append(f'<span class="badge text-bg-light border">🍽 {esc(sc)} servings</span>')
    if recipe["rating"] is not None and recipe["rating_count"]:
        pct = round(recipe["rating"] * 100)
        bits.append(
            f'<span class="badge text-bg-light border">👍 {pct}% '
            f'({esc(recipe["rating_count"])})</span>'
        )
    price = recipe["price_per_serving"]
    if price:
        bits.append(f'<span class="badge text-bg-light border">${price/100:.2f}/serving</span>')
    if recipe["is_pro"]:
        bits.append('<span class="badge text-bg-warning">Pro</span>')
    return " ".join(bits)


def render_recipe(recipe, instructions, line_items, cookware, nutrition, categories, recipe_cats):
    vid = recipe["variant_id"]
    path = recipe_path(recipe)
    parts = [f'<h1 class="mb-2">{esc(recipe["name"])}</h1>']

    tags = []
    for cid in sorted(recipe_cats.get(vid, [])):
        cat = categories[cid]
        href = rel(path, cat_path(cat))
        tags.append(
            f'<a class="badge text-bg-secondary text-decoration-none" '
            f'href="{esc(href)}">{esc(cat_label(cat))}</a>'
        )
    if tags:
        parts.append(f'<div class="mb-2">{" ".join(tags)}</div>')

    badges = meta_badges(recipe)
    if badges:
        parts.append(f'<div class="mb-4 d-flex flex-wrap gap-2">{badges}</div>')

    parts.append('<div class="row g-4">')

    # Ingredients column
    ing_rows = []
    for qty, name in line_items.get(vid, []):
        q = f'<span class="fw-semibold me-1">{esc(qty)}</span>' if qty else ""
        ing_rows.append(f'<li class="list-group-item">{q}{esc(name)}</li>')
    parts.append(
        '<div class="col-lg-4"><div class="card"><div class="card-header fw-bold">'
        'Ingredients</div><ul class="list-group list-group-flush">'
        + ("".join(ing_rows) or '<li class="list-group-item text-body-secondary">None listed</li>')
        + "</ul></div>"
    )
    # Cookware under ingredients
    cw = cookware.get(vid, [])
    if cw:
        chips = " ".join(
            f'<span class="badge text-bg-light border me-1 mb-1">{esc(c)}</span>' for c in cw
        )
        parts.append(
            '<div class="card mt-4"><div class="card-header fw-bold">Cookware</div>'
            f'<div class="card-body">{chips}</div></div>'
        )
    parts.append("</div>")  # end ingredients column

    # Instructions column
    steps = []
    for i, (primary, secondary) in enumerate(instructions.get(vid, []), 1):
        sub = ""
        if secondary and secondary.strip():
            lines = "<br>".join(esc(s) for s in secondary.split("\n") if s.strip())
            sub = f'<div class="small text-body-secondary mt-1">{lines}</div>'
        steps.append(
            '<li class="list-group-item d-flex align-items-start">'
            f'<span class="badge text-bg-primary rounded-pill me-3 mt-1">{i}</span>'
            f'<div>{esc(primary)}{sub}</div></li>'
        )
    parts.append(
        '<div class="col-lg-8"><div class="card"><div class="card-header fw-bold">'
        'Instructions</div><ol class="list-group list-group-flush">'
        + ("".join(steps) or '<li class="list-group-item text-body-secondary">None listed</li>')
        + "</ol></div>"
    )

    # Nutrition (key facts + full table)
    nut = nutrition.get(vid, {})
    cards = []
    for key, label, unit in KEY_NUTRIENTS:
        if key in nut and nut[key] is not None:
            cards.append(
                '<div class="col"><div class="border rounded p-2 text-center h-100 bg-body">'
                f'<div class="fs-5 fw-bold">{fmt_num(nut[key])}<small class="text-body-secondary"> {unit}</small></div>'
                f'<div class="small text-body-secondary">{esc(label)}</div></div></div>'
            )
    nut_html = ['<div class="card mt-4"><div class="card-header fw-bold">Nutrition (per serving)</div>',
                '<div class="card-body">']
    if cards:
        nut_html.append('<div class="row row-cols-2 row-cols-md-3 g-2 mb-3">' + "".join(cards) + "</div>")
    full_rows = "".join(
        f'<tr><td>{esc(nutrient_label(k))}</td>'
        f'<td class="text-end">{fmt_num(nut[k])} {esc(nutrient_unit(k))}</td></tr>'
        for k in sorted(nut) if nut[k] is not None
    )
    if full_rows:
        nut_html.append(
            '<details><summary class="text-primary" style="cursor:pointer">'
            'Full nutrient breakdown</summary>'
            '<div class="table-responsive mt-2"><table class="table table-sm table-striped mb-0">'
            f'<tbody>{full_rows}</tbody></table></div></details>'
        )
    nut_html.append("</div></div>")
    parts.append("".join(nut_html))

    parts.append("</div>")  # end instructions column
    parts.append("</div>")  # end row

    back = rel(path, OUT / "index.html")
    parts.insert(0, f'<a href="{esc(back)}" class="btn btn-sm btn-outline-secondary mb-3">&larr; All recipes</a>')

    return page(recipe["name"], "\n".join(parts), depth=1)


TABLE_JS = """
<style>
#recipe-table tbody tr[hidden]{display:none!important}
#recipe-table th.sortable{cursor:pointer;white-space:nowrap;user-select:none}
#recipe-table th.sortable::after{content:"\\2195";opacity:.35;margin-left:.35em}
#recipe-table th.sortable[data-active="asc"]::after{content:"\\2191";opacity:1}
#recipe-table th.sortable[data-active="desc"]::after{content:"\\2193";opacity:1}
</style>
<script>
(function(){
  var table = document.getElementById('recipe-table');
  if(!table) return;
  var tbody = table.tBodies[0];
  var rows = Array.prototype.slice.call(tbody.rows);
  var input = document.getElementById('recipe-filter');
  var count = document.getElementById('recipe-count');

  function applyFilter(){
    var q = input ? input.value.toLowerCase() : '';
    var shown = 0;
    rows.forEach(function(tr){
      var match = tr.getAttribute('data-name').indexOf(q) !== -1;
      tr.hidden = !match;
      if(match) shown++;
    });
    if(count) count.textContent = shown;
  }

  function sortBy(th){
    var key = th.getAttribute('data-key');
    var type = th.getAttribute('data-type');
    var dir = th.getAttribute('data-dir') === 'asc' ? 'desc' : 'asc';
    th.setAttribute('data-dir', dir);
    var sign = dir === 'asc' ? 1 : -1;
    rows.sort(function(a, b){
      var av = a.getAttribute('data-' + key), bv = b.getAttribute('data-' + key);
      if(type === 'num'){
        // blanks always sort to the bottom regardless of direction
        var ae = av === '', be = bv === '';
        if(ae && be) return 0;
        if(ae) return 1;
        if(be) return -1;
        return (parseFloat(av) - parseFloat(bv)) * sign;
      }
      return av < bv ? -sign : av > bv ? sign : 0;
    });
    rows.forEach(function(tr){ tbody.appendChild(tr); });
    table.querySelectorAll('th.sortable').forEach(function(h){ h.removeAttribute('data-active'); });
    th.setAttribute('data-active', dir);
  }

  table.querySelectorAll('th.sortable').forEach(function(th){
    th.addEventListener('click', function(){ sortBy(th); });
  });
  if(input) input.addEventListener('input', applyFilter);
})();
</script>
"""


def render_category(cat, members, recipes, categories, recipe_cats):
    path = cat_path(cat)
    label = cat_label(cat)
    rows = []
    for vid in sorted(members, key=lambda v: (recipes[v]["name"] or "").lower()):
        r = recipes[vid]
        href = rel(path, recipe_path(r))

        time_val = r["cooking_minutes"] if r["cooking_minutes"] else ""
        time_cell = f'{esc(r["cooking_minutes"])} min' if r["cooking_minutes"] else "—"

        if r["rating"] is not None and r["rating_count"]:
            rating_val = r["rating"]
            rating_cell = (
                f'{round(r["rating"]*100)}% '
                f'<span class="text-body-secondary small">({esc(r["rating_count"])})</span>'
            )
        else:
            rating_val = ""
            rating_cell = "—"

        other = " ".join(
            f'<span class="badge text-bg-light border">{esc(cat_label(categories[cid]))}</span>'
            for cid in sorted(recipe_cats.get(vid, [])) if cid != cat["id"]
        )
        rows.append(
            f'<tr data-name="{esc((r["name"] or "").lower())}" '
            f'data-time="{esc(time_val)}" data-rating="{esc(rating_val)}">'
            f'<td><a class="fw-semibold text-decoration-none" href="{esc(href)}">{esc(r["name"])}</a></td>'
            f'<td class="text-end" data-order="{esc(rating_val)}">{rating_cell}</td>'
            f'<td class="text-end" data-order="{esc(time_val)}">{time_cell}</td>'
            f'<td>{other}</td></tr>'
        )

    back = rel(path, OUT / "index.html")
    body = f"""
<a href="{esc(back)}" class="btn btn-sm btn-outline-secondary mb-3">&larr; Home</a>
<h1 class="mb-1">{esc(label)}</h1>
<p class="text-body-secondary"><span id="recipe-count">{len(members)}</span> recipes</p>
<input id="recipe-filter" type="search" class="form-control mb-3" placeholder="Filter by name…" autocomplete="off">
<div class="table-responsive shadow-sm">
<table id="recipe-table" class="table table-striped table-hover align-middle bg-body mb-0">
<thead class="table-light">
<tr>
<th role="button" class="sortable" data-key="name" data-type="text">Recipe</th>
<th role="button" class="sortable text-end" data-key="rating" data-type="num" data-dir="desc">Approval</th>
<th role="button" class="sortable text-end" data-key="time" data-type="num" data-dir="asc">Time</th>
<th>Tags</th>
</tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</div>
{TABLE_JS}
"""
    return page(f"{label} recipes", body, depth=1)


def render_index(categories, cat_members, total):
    def card_group(kind):
        cards = []
        cats = sorted(
            (c for c in categories.values() if c["kind"] == kind),
            key=lambda c: -len(cat_members.get(c["id"], [])),
        )
        for c in cats:
            n = len(cat_members.get(c["id"], []))
            if not n:
                continue
            href = rel(OUT / "index.html", cat_path(c))
            cards.append(
                '<div class="col"><a class="text-decoration-none" '
                f'href="{esc(href)}"><div class="card h-100 shadow-sm">'
                '<div class="card-body">'
                f'<h5 class="card-title mb-1">{esc(cat_label(c))}</h5>'
                f'<p class="card-text text-body-secondary mb-0">{n} recipes</p>'
                "</div></div></a></div>"
            )
        return "".join(cards)

    body = f"""
<div class="p-4 mb-4 bg-body rounded-3 border text-center">
  <h1 class="display-6 fw-bold">🍋 Recipe Catalog</h1>
  <p class="lead text-body-secondary mb-0">{total} recipes to browse</p>
</div>
<h2 class="h4 mb-3">By meal type</h2>
<div class="row row-cols-1 row-cols-sm-2 row-cols-lg-3 g-3 mb-5">
{card_group("ruleset")}
</div>
<h2 class="h4 mb-3">By food category</h2>
<div class="row row-cols-1 row-cols-sm-2 row-cols-lg-3 g-3">
{card_group("food_category")}
</div>
"""
    return page("Recipe Catalog", body, depth=0)


def main():
    conn = sqlite3.connect(DB_PATH)
    (recipes, instructions, line_items, cookware, nutrition,
     categories, cat_members, recipe_cats) = load_data(conn)
    conn.close()

    (OUT / "recipes").mkdir(parents=True, exist_ok=True)
    (OUT / "categories").mkdir(parents=True, exist_ok=True)
    (OUT / ".nojekyll").write_text("")

    written = 0
    for recipe in recipes.values():
        recipe_path(recipe).write_text(
            render_recipe(recipe, instructions, line_items, cookware,
                          nutrition, categories, recipe_cats),
            encoding="utf-8",
        )
        written += 1

    for cid, members in cat_members.items():
        cat = categories[cid]
        cat_path(cat).write_text(
            render_category(cat, members, recipes, categories, recipe_cats),
            encoding="utf-8",
        )
        written += 1

    (OUT / "index.html").write_text(
        render_index(categories, cat_members, len(recipes)), encoding="utf-8"
    )
    written += 1

    print(f"Wrote {written} pages to {OUT}/ "
          f"({len(recipes)} recipes, {len(cat_members)} categories, 1 index).")


if __name__ == "__main__":
    main()
