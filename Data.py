"""
Business Profit Data Cleaner + Detail Viewer
============================================
How to run (VS Code terminal):
    python clean_business_data.py
    (or)  python clean_business_data.py path/to/file.csv

What this script does:
 1. Loads the CSV (with errors)
 2. Finds and fixes all errors
 3. Prints the full cleaning report in the terminal
 4. Automatically creates new files:
        business_profit_100_CLEANED.csv
        cleaning_report.txt
 5. Opens a search mode - type any detail
    (ID, business name, region, type, month) and see everything about it.
"""

import sys
import difflib
from pathlib import Path

import pandas as pd

# ------------------------------------------------------------------ settings
DEFAULT_FILE = "business_profit_100_with_errors.csv"
OUT_CSV = "business_profit_100_CLEANED.csv"
OUT_REPORT = "cleaning_report.txt"

VALID_TYPES = ["Services", "E-commerce", "Manufacturing", "Restaurant", "Retail", "Wholesale"]
VALID_REGIONS = ["East", "West", "North", "South", "Central"]
VALID_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
MONEY_COLS = ["Revenue_INR", "Expenses_INR", "Profit_INR"]

log = []  # (record, column, problem, fix)


def note(record_id, column, problem, fix):
    log.append((record_id, column, problem, fix))


# ------------------------------------------------------------------ helpers
def fix_category(value, valid, column, rid):
    """Fixes spelling / case (Nroth -> North, RETAIL -> Retail)."""
    if pd.isna(value) or str(value).strip() == "":
        note(rid, column, "Value missing", "Left blank (data not available)")
        return pd.NA
    original = str(value).strip()
    lookup = {v.lower(): v for v in valid}
    if original.lower() in lookup:
        fixed = lookup[original.lower()]
    else:
        match = difflib.get_close_matches(original.lower(), list(lookup), n=1, cutoff=0.6)
        fixed = lookup[match[0]] if match else original
    if fixed != original:
        note(rid, column, f"Wrong spelling/case '{original}'", f"Changed to '{fixed}'")
    return fixed


def margin(profit, revenue):
    return round(profit / revenue * 100, 2) if revenue else float("nan")


# ------------------------------------------------------------------ cleaning
def clean(df):
    df = df.copy()
    df.columns = [c.strip() for c in df.columns]

    # remove extra spaces
    for c in df.columns:
        df[c] = df[c].astype("string").str.strip()

    # numbers
    df["Record_ID"] = pd.to_numeric(df["Record_ID"], errors="coerce")
    for c in MONEY_COLS + ["Profit_Margin_Percent"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---- duplicate Record_ID -> replace with the missing number
    all_ids = set(range(1, len(df) + 1))
    missing_ids = sorted(all_ids - set(df["Record_ID"].dropna().astype(int)))
    seen = set()
    for i in df.index:
        rid = df.at[i, "Record_ID"]
        if pd.isna(rid) or int(rid) in seen:
            new = missing_ids.pop(0) if missing_ids else int(df["Record_ID"].max()) + 1
            note(new, "Record_ID", f"Duplicate/missing ID ({'' if pd.isna(rid) else int(rid)})", f"Changed to {new}")
            df.at[i, "Record_ID"] = new
            rid = new
        seen.add(int(rid))
    df["Record_ID"] = df["Record_ID"].astype(int)

    # ---- duplicate Business_Name -> name based on Record_ID
    seen_names = set()
    for i in df.index:
        name, rid = df.at[i, "Business_Name"], df.at[i, "Record_ID"]
        if pd.isna(name) or name in seen_names:
            new = f"Business_{rid:03d}"
            note(rid, "Business_Name", f"Duplicate/missing name '{name}'", f"Changed to '{new}'")
            df.at[i, "Business_Name"] = new
            name = new
        seen_names.add(name)

    # ---- text columns
    for i in df.index:
        rid = df.at[i, "Record_ID"]
        df.at[i, "Business_Type"] = fix_category(df.at[i, "Business_Type"], VALID_TYPES, "Business_Type", rid)
        df.at[i, "Region"] = fix_category(df.at[i, "Region"], VALID_REGIONS, "Region", rid)
        df.at[i, "Month"] = fix_category(df.at[i, "Month"], VALID_MONTHS, "Month", rid)

    # ---- negative values (sign mistake)
    for i in df.index:
        for c in MONEY_COLS:
            v = df.at[i, c]
            if pd.notna(v) and v < 0:
                note(df.at[i, "Record_ID"], c, f"Negative value ({v:,.0f})", f"Changed to {abs(v):,.0f}")
                df.at[i, c] = abs(v)

    # ---- Revenue - Expenses = Profit (make all three consistent)
    for i in df.index:
        rid = df.at[i, "Record_ID"]
        rev, exp, pro = (df.at[i, c] for c in MONEY_COLS)
        given_margin = df.at[i, "Profit_Margin_Percent"]

        if pd.isna(rev) and pd.notna(exp) and pd.notna(pro):
            rev = exp + pro
            df.at[i, "Revenue_INR"] = rev
            note(rid, "Revenue_INR", "Value missing", f"Expenses + Profit = {rev:,.0f}")
            continue
        if pd.isna(exp) and pd.notna(rev) and pd.notna(pro):
            df.at[i, "Expenses_INR"] = rev - pro
            note(rid, "Expenses_INR", "Value missing", f"Revenue - Profit = {rev - pro:,.0f}")
            continue
        if pd.isna(pro) and pd.notna(rev) and pd.notna(exp):
            df.at[i, "Profit_INR"] = rev - exp
            note(rid, "Profit_INR", "Value missing", f"Revenue - Expenses = {rev - exp:,.0f}")
            continue
        if pd.isna(rev) or pd.isna(exp) or pd.isna(pro):
            continue

        if abs(rev - exp - pro) > 1:  # mismatch -> find which value is wrong
            candidates = {
                "Profit_INR": (rev, exp, rev - exp),
                "Revenue_INR": (exp + pro, exp, pro),
                "Expenses_INR": (rev, rev - pro, pro),
            }
            chosen = None
            for col, (r, e, p) in candidates.items():
                if pd.notna(given_margin) and r > 0 and abs(margin(p, r) - given_margin) < 0.05:
                    chosen = col
                    break
            chosen = chosen or "Profit_INR"
            r, e, p = candidates[chosen]
            old = df.at[i, chosen]
            df.at[i, "Revenue_INR"], df.at[i, "Expenses_INR"], df.at[i, "Profit_INR"] = r, e, p
            note(rid, chosen, f"Revenue/Expenses/Profit do not match ({old:,.0f})",
                 f"Changed to {df.at[i, chosen]:,.0f}")

    # ---- always recalculate profit margin
    for i in df.index:
        rid = df.at[i, "Record_ID"]
        rev, pro = df.at[i, "Revenue_INR"], df.at[i, "Profit_INR"]
        if pd.isna(rev) or pd.isna(pro):
            continue
        new = margin(pro, rev)
        old = df.at[i, "Profit_Margin_Percent"]
        if pd.isna(old) or abs(old - new) > 0.05:
            note(rid, "Profit_Margin_Percent", f"Wrong margin ({old})", f"Changed to {new}")
        df.at[i, "Profit_Margin_Percent"] = new

    for c in MONEY_COLS:
        df[c] = df[c].round(0).astype("Int64")
    df["Status"] = df["Profit_INR"].apply(
        lambda p: "LOSS" if p < 0 else ("BREAK-EVEN" if p == 0 else "PROFIT"))
    return df.sort_values("Record_ID").reset_index(drop=True)


# ------------------------------------------------------------------ display
LINE = "=" * 72


def inr(x):
    return "N/A" if pd.isna(x) else f"Rs {int(x):,}"


def show_card(row):
    print("\n" + LINE)
    print(f"  BUSINESS DETAIL  -  {row['Business_Name']}")
    print(LINE)
    print(f"  Record ID        : {row['Record_ID']}")
    print(f"  Business Name    : {row['Business_Name']}")
    print(f"  Business Type    : {row['Business_Type']}")
    print(f"  Region           : {row['Region']}")
    print(f"  Month            : {row['Month']}")
    print(f"  Revenue          : {inr(row['Revenue_INR'])}")
    print(f"  Expenses         : {inr(row['Expenses_INR'])}")
    print(f"  Profit           : {inr(row['Profit_INR'])}")
    print(f"  Profit Margin    : {row['Profit_Margin_Percent']}%")
    print(f"  Status           : {row['Status']}")
    print(LINE)


def show_table(rows):
    cols = ["Record_ID", "Business_Name", "Business_Type", "Region", "Month",
            "Revenue_INR", "Expenses_INR", "Profit_INR", "Profit_Margin_Percent", "Status"]
    with pd.option_context("display.width", 250, "display.max_columns", 50, "display.max_rows", 500):
        print(rows[cols].to_string(index=False))


def summary(df, title="SUMMARY"):
    print("\n" + LINE)
    print(f"  {title}   ({len(df)} records)")
    print(LINE)
    print(f"  Total Revenue    : {inr(df['Revenue_INR'].sum())}")
    print(f"  Total Expenses   : {inr(df['Expenses_INR'].sum())}")
    print(f"  Total Profit     : {inr(df['Profit_INR'].sum())}")
    print(f"  Avg Margin       : {df['Profit_Margin_Percent'].mean():.2f}%")
    n_loss = int((df["Status"] == "LOSS").sum())
    print(f"  Profitable       : {int((df['Status'] == 'PROFIT').sum())}")
    print(f"  Loss-making      : {n_loss}" + ("   (no losses in this data)" if n_loss == 0 else ""))
    if n_loss:
        print(f"  Total Loss       : {inr(df.loc[df['Status'] == 'LOSS', 'Profit_INR'].sum())}")
    best = df.loc[df["Profit_INR"].idxmax()]
    worst = df.loc[df["Profit_INR"].idxmin()]
    print(f"  Highest Profit   : {best['Business_Name']} ({inr(best['Profit_INR'])})")
    print(f"  Lowest Profit    : {worst['Business_Name']} ({inr(worst['Profit_INR'])})")
    for col in ["Business_Type", "Region", "Month"]:
        print(f"\n  By {col} (Total Profit | Avg Margin | Count):")
        g = df.groupby(col).agg(profit=("Profit_INR", "sum"),
                                margin=("Profit_Margin_Percent", "mean"),
                                n=("Record_ID", "count")).sort_values("profit", ascending=False)
        for k, r in g.iterrows():
            print(f"    {k:<15} {inr(r['profit']):>16} | {r['margin']:6.2f}% | {r['n']}")
    print(LINE)


def cleaning_report(raw, cleaned):
    lines = [LINE, "  CLEANING REPORT", LINE,
             f"  Original rows : {len(raw)}", f"  Cleaned rows  : {len(cleaned)}",
             f"  Total fixes   : {len(log)}", ""]
    lines.append(f"  {'Record':<7}{'Column':<24}{'Problem':<50}Fix")
    lines.append("  " + "-" * 105)
    for rid, col, prob, fix in sorted(log, key=lambda x: (x[0], x[1])):
        lines.append(f"  {rid:<7}{col:<24}{prob:<50}{fix}")
    lines.append(LINE)
    return "\n".join(lines)


# ------------------------------------------------------------------ search
HELP = """
  What you can type:
    5                 -> full details of Record ID 5
    Business_005      -> full details of that business
    East / South ...  -> all records of that Region
    Retail / Services -> all records of that Business Type
    March / June ...  -> all records of that Month
    East Retail       -> several words = all of them must match
    summary           -> full summary
    loss              -> all loss-making businesses
    profit            -> all profitable businesses
    lowest            -> 10 businesses with the lowest profit
    all               -> all records
    errors            -> what was fixed
    help              -> show this menu
    exit              -> quit
"""


def search(df, text):
    text = text.strip().lower()
    if text.isdigit():
        hit = df[df["Record_ID"] == int(text)]
        if hit.empty:
            hit = df[df["Business_Name"].str.lower().str.contains(text.zfill(3))]
        return hit
    exact = df[df["Business_Name"].str.lower() == text]
    if len(exact):
        return exact
    mask = pd.Series(True, index=df.index)
    for word in text.split():
        m = pd.Series(False, index=df.index)
        for c in ["Business_Name", "Business_Type", "Region", "Month"]:
            m |= df[c].astype("string").str.lower().str.contains(word, na=False, regex=False)
        mask &= m
    return df[mask]


def interactive(df, report_text):
    print(HELP)
    while True:
        try:
            q = input("Enter a detail (help / exit) >>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break
        if not q:
            continue
        ql = q.lower()
        if ql in ("exit", "quit", "q"):
            print("Bye!")
            break
        if ql == "help":
            print(HELP)
        elif ql == "summary":
            summary(df)
        elif ql == "loss":
            hit = df[df["Status"] == "LOSS"]
            if hit.empty:
                print("  No business is making a loss. The 5 lowest-profit businesses:")
                show_table(df.nsmallest(5, "Profit_INR"))
            else:
                show_table(hit)
        elif ql == "profit":
            show_table(df[df["Status"] == "PROFIT"])
        elif ql == "lowest":
            show_table(df.nsmallest(10, "Profit_INR"))
        elif ql == "all":
            show_table(df)
        elif ql == "errors":
            print(report_text)
        else:
            hit = search(df, q)
            if hit.empty:
                print("  Nothing found. Type 'help' to see what you can search.")
            elif len(hit) == 1:
                show_card(hit.iloc[0])
            else:
                print(f"\n  {len(hit)} records found:\n")
                show_table(hit)
                summary(hit, f"SUMMARY for '{q}'")


# ------------------------------------------------------------------ main
def main():
    base = Path(__file__).resolve().parent
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
    else:
        path = next((p for p in (base / DEFAULT_FILE, Path.cwd() / DEFAULT_FILE) if p.exists()),
                    base / DEFAULT_FILE)
    if not path.exists():
        sys.exit(f"File not found: {path}\nPut the CSV in the same folder as this script or pass its path as an argument.")
    path = path.resolve()

    raw = pd.read_csv(path, dtype=str)
    print(f"\nFile loaded: {path.name}  ({len(raw)} rows, {len(raw.columns)} columns)")
    print("Missing values (before cleaning):")
    print(raw.isna().sum()[raw.isna().sum() > 0].to_string() or "  none")

    cleaned = clean(raw)
    report_text = cleaning_report(raw, cleaned)
    print("\n" + report_text)

    out_dir = path.parent
    out_csv, out_rep = out_dir / OUT_CSV, out_dir / OUT_REPORT
    cleaned.to_csv(out_csv, index=False)
    out_rep.write_text(report_text, encoding="utf-8")
    ok = out_csv.exists() and out_csv.stat().st_size > 0
    print(f"\n{'[OK] New CLEANED file created automatically' if ok else '[ERROR] File was not created'}")
    print(f"  Cleaned CSV : {out_csv}")
    print(f"  Report      : {out_rep}")
    print("  (If you don't see it in VS Code, refresh the Explorer panel)")
    print(f"Remaining missing values: {int(cleaned.isna().sum().sum())}")

    summary(cleaned, "CLEANED DATA SUMMARY")
    interactive(cleaned, report_text)


if __name__ == "__main__":
    main()