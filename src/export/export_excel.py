"""
export_excel.py  --  Gold layer -> Excel workbook

Produces output/excel/job_market_scorecard_<date>.xlsx (+ _latest.xlsx copy):

  KPI Scorecard   KPI tiles driven by LIVE Excel formulas over tblJobs
  Role Summary    pivot-style summary by role family (COUNTIFS / AVERAGEIFS)
  Skill x Role    top-N skills x role families: counts + % of role's jobs (heatmap)
  Salary by State median salary, state x role (values from gold.salary_by_state_role)
  Jobs Data       tblJobs   (Excel Table -> point a PivotTable / Power Query at it)
  Skills Data     tblSkills (Excel Table)
  Run Log         tblRuns   (last 14 pipeline runs from ops.pipeline_runs)

Design notes
  * Formulas are real Excel formulas so the workbook recalculates if rows change.
    Cached values are also written so previewers that don't recalc still show numbers.
  * "Unique companies" and the salary-by-state grid are values from the Gold layer
    (a DISTINCT-count formula is O(n^2) in classic Excel; medians-by-group need arrays).
  * Native PivotTables cannot be authored by Python libraries. Insert one on tblJobs
    (Insert > PivotTable > Table/Range: tblJobs), or use the Power Query workbook
    (powerbi/queries.pq) for a refreshable version. See README.

Usage:  python src/export/export_excel.py [--out PATH] [--top-skills 25]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from xlsxwriter.utility import xl_col_to_name

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR / "src" / "db"))
from load_to_db import get_engine  # noqa: E402  (reuses .env-based engine, no duplicated credentials)

OUT_DIR = BASE_DIR / "output" / "excel"
FONT = "Arial"

NAVY, TEAL, LIGHT, GREY = "#1F3A5F", "#2A7F8E", "#EEF3F8", "#6B7280"
GREEN_BG, GREEN_FG, RED_BG, RED_FG = "#DFF3E4", "#1B6B35", "#FBE0E0", "#9B1C1C"


# --------------------------------------------------------------------------
# Extract
# --------------------------------------------------------------------------
def read_gold(engine) -> dict[str, pd.DataFrame]:
    jobs = pd.read_sql(
        """SELECT job_pk, title, role_family, company_name, state_name, location_name,
                  posting_date, salary_min, salary_max, salary_avg, salary_basis, has_salary,
                  contract_time, skill_count, redirect_url
           FROM gold.fct_jobs
           ORDER BY posting_date DESC NULLS LAST, job_pk""", engine)
    skills = pd.read_sql("SELECT job_pk, skill_name, role_family FROM gold.fct_job_skills", engine)
    salary = pd.read_sql("SELECT * FROM gold.salary_by_state_role", engine)
    runs = pd.read_sql(
        """SELECT run_id, run_ts, status, raw_records, jobs_total, jobs_added, skills, skill_links
           FROM ops.pipeline_runs ORDER BY run_ts DESC LIMIT 14""", engine)

    # NUMERIC comes back as Decimal (object dtype) -> real floats; dates -> datetime64
    for col in ["salary_min", "salary_max", "salary_avg"]:
        jobs[col] = pd.to_numeric(jobs[col], errors="coerce")
    for col in ["jobs", "jobs_with_salary", "avg_salary", "median_salary"]:
        salary[col] = pd.to_numeric(salary[col], errors="coerce")
    jobs["posting_date"] = pd.to_datetime(jobs["posting_date"])
    jobs["contract_time"] = jobs["contract_time"].fillna("")
    runs["run_ts"] = pd.to_datetime(runs["run_ts"]).dt.tz_localize(None)
    return {"jobs": jobs, "skills": skills, "salary": salary, "runs": runs}


# --------------------------------------------------------------------------
# Workbook
# --------------------------------------------------------------------------
def build_workbook(path: Path, data: dict[str, pd.DataFrame], top_n: int = 25, min_salary_n: int = 3) -> None:
    jobs, skills, salary, runs = data["jobs"], data["skills"], data["salary"], data["runs"]
    if jobs.empty:
        raise ValueError("gold.fct_jobs is empty - nothing to export.")
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    with pd.ExcelWriter(
        path, engine="xlsxwriter",
        datetime_format="yyyy-mm-dd", date_format="yyyy-mm-dd",
        engine_kwargs={"options": {
            "strings_to_urls": False,          # 65k-hyperlink-per-sheet limit
            "remove_timezone": True,
            "default_format_properties": {"font_name": FONT, "font_size": 10},
        }},
    ) as xw:
        wb = xw.book
        F = lambda **kw: wb.add_format({"font_name": FONT, "font_size": 10, **kw})  # noqa: E731

        title = F(bold=True, font_size=18, font_color=NAVY)
        sub = F(font_color=GREY, italic=True)
        hdr = F(bold=True, font_color="white", bg_color=NAVY, border=1, align="center", valign="vcenter", text_wrap=True)
        lbl = F(bold=True, font_color=GREY, font_size=9, bg_color=LIGHT, align="center", valign="vcenter", top=2, top_color=TEAL)
        val_int = F(bold=True, font_size=20, font_color=NAVY, bg_color=LIGHT, align="center", valign="vcenter", num_format="#,##0")
        val_pct = F(bold=True, font_size=20, font_color=NAVY, bg_color=LIGHT, align="center", valign="vcenter", num_format="0.0%")
        val_pcts = F(bold=True, font_size=20, font_color=NAVY, bg_color=LIGHT, align="center", valign="vcenter", num_format="+0.0%;-0.0%;0.0%")
        val_usd = F(bold=True, font_size=20, font_color=NAVY, bg_color=LIGHT, align="center", valign="vcenter", num_format="$#,##0")
        val_dec = F(bold=True, font_size=20, font_color=NAVY, bg_color=LIGHT, align="center", valign="vcenter", num_format="0.0")
        val_date = F(bold=True, font_color=NAVY, num_format="yyyy-mm-dd", align="left")
        txt, txt_b = F(), F(bold=True)
        n0, n1, pct, usd = F(num_format="#,##0"), F(num_format="0.0"), F(num_format="0.0%"), F(num_format="$#,##0")
        tot_lbl = F(bold=True, top=1, bg_color=LIGHT)
        tot_n0 = F(bold=True, top=1, bg_color=LIGHT, num_format="#,##0")
        tot_pct = F(bold=True, top=1, bg_color=LIGHT, num_format="0.0%")
        tot_usd = F(bold=True, top=1, bg_color=LIGHT, num_format="$#,##0")
        tot_n1 = F(bold=True, top=1, bg_color=LIGHT, num_format="0.0")
        good, bad = F(bg_color=GREEN_BG, font_color=GREEN_FG), F(bg_color=RED_BG, font_color=RED_FG)
        note = F(font_color=GREY, text_wrap=True, valign="top")

        # Create sheets up-front so the scorecard is the first tab
        names = ["KPI Scorecard", "Role Summary", "Skill x Role", "Salary by State",
                 "Jobs Data", "Skills Data", "Run Log"]
        for n in names:
            xw.sheets[n] = wb.add_worksheet(n)
        ws_k, ws_r, ws_s, ws_st, ws_j, ws_sk, ws_log = (xw.sheets[n] for n in names)
        ws_k.activate()
        for _ws in (ws_k, ws_r, ws_s, ws_st):          # print-friendly: landscape, 1 page wide
            _ws.set_landscape()
            _ws.fit_to_pages(1, 0)

        # ---------------- data tables ----------------
        def write_table(ws, sheet, df, tname, widths: dict[str, int], fmts: dict[str, object] | None = None):
            df.to_excel(xw, sheet_name=sheet, index=False, header=False, startrow=1)
            ws.add_table(0, 0, len(df), len(df.columns) - 1, {
                "name": tname, "style": "Table Style Medium 2",
                "columns": [{"header": c} for c in df.columns]})
            for i, c in enumerate(df.columns):
                ws.set_column(i, i, widths.get(c, 14), (fmts or {}).get(c))
            ws.freeze_panes(1, 0)

        write_table(ws_j, "Jobs Data", jobs, "tblJobs",
                    {"title": 42, "role_family": 18, "company_name": 28, "state_name": 16, "location_name": 26,
                     "posting_date": 12, "redirect_url": 30},
                    {"salary_min": usd, "salary_max": usd, "salary_avg": usd})
        write_table(ws_sk, "Skills Data", skills, "tblSkills", {"skill_name": 24, "role_family": 20})
        if runs.empty:
            ws_log.write(0, 0, "No runs logged yet (ops.pipeline_runs is empty).", txt)
        else:
            write_table(ws_log, "Run Log", runs, "tblRuns", {"run_id": 34, "run_ts": 20})

        # ---------------- cached values (pandas) ----------------
        total = len(jobs)
        anchor = jobs["posting_date"].max()
        d = jobs["posting_date"]
        last7 = int((d > anchor - pd.Timedelta(days=7)).sum())
        prior7 = int(((d > anchor - pd.Timedelta(days=14)) & (d <= anchor - pd.Timedelta(days=7))).sum())
        wow = (last7 / prior7 - 1) if prior7 else "n/a"
        n_sal = int(jobs["salary_avg"].notna().sum())
        med_sal = float(jobs["salary_avg"].median()) if n_sal else "n/a"
        ct = jobs["contract_time"]
        ft_share = (ct.eq("full_time").sum() / ct.ne("").sum()) if ct.ne("").any() else "n/a"
        companies = int(jobs["company_name"].nunique())

        # ---------------- KPI Scorecard ----------------
        ws_k.hide_gridlines(2)
        ws_k.set_column("A:A", 2)
        ws_k.set_column("B:I", 13)
        ws_k.set_row(1, 28)
        ws_k.write("B2", "Job Market Analytics - KPI Scorecard", title)
        ws_k.write("B3", f"Source: Adzuna API -> PostgreSQL gold layer | generated {generated}", sub)

        ws_k.write("B5", "Data through", txt_b)
        # cached value of a date formula must be an Excel serial number, NOT a datetime
        anchor_serial = (anchor - pd.Timestamp("1899-12-30")).days
        ws_k.write_formula("C5", "=MAX(tblJobs[posting_date])", val_date, anchor_serial)
        ANCHOR = "$C$5"

        def tile(row, col, label, formula, fmt, cached):
            ws_k.merge_range(row, col, row, col + 1, label, lbl)
            ws_k.merge_range(row + 1, col, row + 1, col + 1, "", fmt)
            ws_k.write_formula(row + 1, col, formula, fmt, cached)
            ws_k.set_row(row + 1, 34)

        T = "COUNTA(tblJobs[job_pk])"
        # Row 1 of tiles (rows 7-8) and row 2 (rows 10-11); 0-indexed rows 6.. / 9..
        tile(6, 1, "TOTAL JOBS", f"={T}", val_int, total)
        tile(6, 3, "POSTED LAST 7 DAYS", f'=COUNTIFS(tblJobs[posting_date],">"&({ANCHOR}-7))', val_int, last7)
        tile(6, 5, "PRIOR 7 DAYS", f'=COUNTIFS(tblJobs[posting_date],">"&({ANCHOR}-14),tblJobs[posting_date],"<="&({ANCHOR}-7))', val_int, prior7)
        tile(6, 7, "WEEK-OVER-WEEK", '=IFERROR(D8/F8-1,"n/a")', val_pcts, wow)
        tile(9, 1, "UNIQUE COMPANIES*", f"={companies}", val_int, companies)
        tile(9, 3, "MEDIAN SALARY", '=IFERROR(MEDIAN(tblJobs[salary_avg]),"n/a")', val_usd, med_sal)
        tile(9, 5, "SALARY DISCLOSED", f"=IFERROR(COUNT(tblJobs[salary_avg])/{T},0)", val_pct, n_sal / total)
        tile(9, 7, "AVG SKILLS / JOB", f"=IFERROR(AVERAGE(tblJobs[skill_count]),0)", val_dec, float(jobs["skill_count"].mean()))
        ws_k.conditional_format("H8:I8", {"type": "cell", "criteria": ">", "value": 0, "format": good})
        ws_k.conditional_format("H8:I8", {"type": "cell", "criteria": "<", "value": 0, "format": bad})

        ws_k.write("B13", "Full-time share (of jobs stating contract time)", txt_b)
        ws_k.write_formula("H13", '=IFERROR(COUNTIFS(tblJobs[contract_time],"full_time")/COUNTIFS(tblJobs[contract_time],"?*"),"n/a")', pct, ft_share)

        # Top 5 skills
        ws_k.write("B15", "Top 5 skills", txt_b)
        ws_k.merge_range(15, 1, 15, 2, "Skill", hdr)
        ws_k.write(15, 3, "Jobs", hdr)
        ws_k.write(15, 4, "% of all jobs", hdr)
        top5 = skills.groupby("skill_name")["job_pk"].nunique().sort_values(ascending=False).head(5)
        for i, (sk, cnt) in enumerate(top5.items()):
            r = 16 + i
            ws_k.merge_range(r, 1, r, 2, sk, txt)
            ws_k.write_formula(r, 3, f'=COUNTIFS(tblSkills[skill_name],B{r + 1})', n0, int(cnt))
            ws_k.write_formula(r, 4, f"=IFERROR(D{r + 1}/{T},0)", pct, cnt / total)

        # Pipeline health
        ws_k.write("G15", "Pipeline health", txt_b)
        if runs.empty:
            ws_k.write("G16", "No runs logged yet", sub)
        else:
            ok = (runs["status"] == "success").mean()
            ws_k.write("G16", "Runs logged (last 14)", txt)
            ws_k.write_formula("I16", "=COUNTA(tblRuns[run_id])", n0, len(runs))
            ws_k.write("G17", "Success rate", txt)
            ws_k.write_formula("I17", '=IFERROR(COUNTIFS(tblRuns[status],"success")/COUNTA(tblRuns[run_id]),0)', pct, float(ok))
            ws_k.write("G18", "Latest run", txt)
            ws_k.write_datetime("I18", runs["run_ts"].iloc[0].to_pydatetime(), F(num_format="mm-dd hh:mm"))

        notes = [
            "Notes",
            "* Unique companies is a value from the Gold layer (a DISTINCT formula is O(n^2) in Excel). Everything else on this tab is a live formula over tblJobs / tblSkills / tblRuns.",
            "Salary figures use EMPLOYER-STATED salaries only. Adzuna estimates most postings' salaries itself (flagged salary_is_predicted); those are excluded. See salary_basis in tblJobs.",
            "Skills come from Adzuna's description snippet (the search API truncates descriptions at 500 characters), so counts understate what full postings request.",
            "role_family is a title-keyword heuristic; skills come from rule-based dictionary matching (not a trained NLP model). Treat both as directional.",
            "For a native PivotTable: Insert > PivotTable > Table/Range = tblJobs.",
        ]
        ws_k.write("B24", notes[0], txt_b)
        for i, n in enumerate(notes[1:]):
            ws_k.merge_range(24 + i, 1, 24 + i, 8, n, note)
            ws_k.set_row(24 + i, 30)

        # ---------------- Role Summary ----------------
        roles = jobs["role_family"].value_counts().index.tolist()
        ws_r.hide_gridlines(2)
        ws_r.set_column("A:A", 24)
        ws_r.set_column("B:G", 14)
        ws_r.write("A1", "Role summary (live formulas over tblJobs)", title)
        heads = ["Role family", "Jobs", "% of jobs", "Jobs w/ salary", "Salary disclosed", "Avg salary", "Avg skills / job"]
        for i, h in enumerate(heads):
            ws_r.write(3, i, h, hdr)
        ws_r.set_row(3, 30)
        first, last = 5, 4 + len(roles)           # Excel rows (1-based)
        for i, role in enumerate(roles):
            r = 4 + i
            x = r + 1
            sub_df = jobs[jobs["role_family"] == role]
            ns = int(sub_df["salary_avg"].notna().sum())
            ws_r.write(r, 0, role, txt)
            ws_r.write_formula(r, 1, f"=COUNTIFS(tblJobs[role_family],$A{x})", n0, len(sub_df))
            ws_r.write_formula(r, 2, f"=IFERROR(B{x}/{T},0)", pct, len(sub_df) / total)
            ws_r.write_formula(r, 3, f'=COUNTIFS(tblJobs[role_family],$A{x},tblJobs[salary_avg],">0")', n0, ns)
            ws_r.write_formula(r, 4, f"=IFERROR(D{x}/B{x},0)", pct, ns / len(sub_df))
            ws_r.write_formula(r, 5, f'=IFERROR(AVERAGEIFS(tblJobs[salary_avg],tblJobs[role_family],$A{x}),"")', usd,
                               float(sub_df["salary_avg"].mean()) if ns else "")
            ws_r.write_formula(r, 6, f'=IFERROR(AVERAGEIFS(tblJobs[skill_count],tblJobs[role_family],$A{x}),"")', n1,
                               float(sub_df["skill_count"].mean()))
        tr = last  # 0-indexed total row
        ws_r.write(tr, 0, "Total", tot_lbl)
        ws_r.write_formula(tr, 1, f"=SUM(B{first}:B{last})", tot_n0, total)
        ws_r.write_formula(tr, 2, f"=SUM(C{first}:C{last})", tot_pct, 1.0)
        ws_r.write_formula(tr, 3, f"=SUM(D{first}:D{last})", tot_n0, n_sal)
        ws_r.write_formula(tr, 4, f"=IFERROR(D{last + 1}/B{last + 1},0)", tot_pct, n_sal / total)
        ws_r.write_formula(tr, 5, '=IFERROR(AVERAGE(tblJobs[salary_avg]),"")', tot_usd,
                           float(jobs["salary_avg"].mean()) if n_sal else "")
        ws_r.write_formula(tr, 6, "=IFERROR(AVERAGE(tblJobs[skill_count]),0)", tot_n1, float(jobs["skill_count"].mean()))
        ws_r.conditional_format(f"B{first}:B{last}", {"type": "data_bar", "bar_color": TEAL, "bar_solid": True})
        ROLE_FIRST, ROLE_LAST = first, last

        # ---------------- Skill x Role ----------------
        top_skills = skills.groupby("skill_name")["job_pk"].nunique().sort_values(ascending=False).head(top_n)
        sk_roles = roles
        ws_s.hide_gridlines(2)
        ws_s.set_column("A:A", 22)
        ws_s.set_column(1, len(sk_roles) + 2, 13)
        ws_s.write("A1", f"Top {len(top_skills)} skills x role family (live COUNTIFS over tblSkills)", title)
        ws_s.write("A2", "Block 1: number of jobs mentioning the skill.  Block 2: % of that role's jobs.", sub)
        # Block 1
        ws_s.write(3, 0, "Skill", hdr)
        for j, role in enumerate(sk_roles):
            ws_s.write(3, 1 + j, role, hdr)
        ws_s.write(3, 1 + len(sk_roles), "All roles", hdr)
        ws_s.set_row(3, 30)
        ws_s.write(4, 0, "Jobs in role", tot_lbl)
        for j, role in enumerate(sk_roles):
            c = xl_col_to_name(1 + j)
            ws_s.write_formula(4, 1 + j, f"=COUNTIFS(tblJobs[role_family],{c}$4)", tot_n0, int((jobs["role_family"] == role).sum()))
        ws_s.write_formula(4, 1 + len(sk_roles), f"={T}", tot_n0, total)
        piv = skills.groupby(["skill_name", "role_family"])["job_pk"].nunique()
        for i, sk in enumerate(top_skills.index):
            r = 5 + i
            x = r + 1
            ws_s.write(r, 0, sk, txt)
            for j, role in enumerate(sk_roles):
                c = xl_col_to_name(1 + j)
                ws_s.write_formula(r, 1 + j, f"=COUNTIFS(tblSkills[skill_name],$A{x},tblSkills[role_family],{c}$4)", n0,
                                   int(piv.get((sk, role), 0)))
            lastc = xl_col_to_name(len(sk_roles))
            ws_s.write_formula(r, 1 + len(sk_roles), f"=SUM(B{x}:{lastc}{x})", n0, int(top_skills[sk]))
        b1_first, b1_last = 6, 5 + len(top_skills)
        ws_s.conditional_format(1 + 4, 1, b1_last - 1, len(sk_roles),
                                {"type": "2_color_scale", "min_color": "#FFFFFF", "max_color": TEAL})
        # Block 2 (% of role's jobs)
        off = b1_last + 3                      # 1-based row of block-2 header
        ws_s.write(off - 1, 0, "Skill (% of role's jobs)", hdr)
        for j, role in enumerate(sk_roles):
            ws_s.write(off - 1, 1 + j, role, hdr)
        ws_s.set_row(off - 1, 30)
        role_jobs = jobs["role_family"].value_counts()
        for i, sk in enumerate(top_skills.index):
            r = off + i
            ws_s.write(r, 0, sk, txt)
            for j, role in enumerate(sk_roles):
                c = xl_col_to_name(1 + j)
                src_row = b1_first + i
                cached = piv.get((sk, role), 0) / role_jobs[role]
                ws_s.write_formula(r, 1 + j, f"=IFERROR({c}{src_row}/{c}$5,0)", pct, float(cached))
        ws_s.conditional_format(off, 1, off + len(top_skills) - 1, len(sk_roles),
                                {"type": "3_color_scale", "min_color": "#FFFFFF", "mid_color": "#BFE3E8", "max_color": NAVY})
        ws_s.freeze_panes(4, 1)

        # ---------------- Salary by State (values from Gold) ----------------
        ws_st.hide_gridlines(2)
        ws_st.set_column("A:A", 20)
        ws_st.set_column("B:J", 15)
        ws_st.write("A1", "Median salary by state x role family", title)
        ws_st.write("A2", f"Values from gold.salary_by_state_role (employer-stated salaries). Blank = fewer than {min_salary_n} postings; "
                          "medians of fewer than ~5 postings are anecdotal. 'Unknown' location excluded.", sub)
        real = salary[salary["state_name"] != "Unknown"]          # 'Unknown' = no state in Adzuna's location data
        s = real[real["jobs_with_salary"] >= min_salary_n]
        top_states = real.groupby("state_name")["jobs"].sum().sort_values(ascending=False).head(15).index
        top_roles = [r for r in roles if r != "Other"][:7]
        p = (s[s["state_name"].isin(top_states) & s["role_family"].isin(top_roles)]
             .pivot_table(index="state_name", columns="role_family", values="median_salary", aggfunc="max")
             .reindex(index=[x for x in top_states if x in set(s["state_name"])], columns=top_roles))
        ws_st.write(3, 0, "State", hdr)
        for j, role in enumerate(top_roles):
            ws_st.write(3, 1 + j, role, hdr)
        ws_st.set_row(3, 30)
        for i, (state, row) in enumerate(p.iterrows()):
            ws_st.write(4 + i, 0, state, txt)
            for j, role in enumerate(top_roles):
                v = row[role]
                if pd.notna(v):
                    ws_st.write_number(4 + i, 1 + j, float(v), usd)
        if len(p):
            ws_st.conditional_format(4, 1, 3 + len(p), len(top_roles),
                                     {"type": "3_color_scale", "min_color": "#FFFFFF", "mid_color": "#BFE3E8", "max_color": TEAL})


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=None, help="output .xlsx path")
    ap.add_argument("--top-skills", type=int, default=25)
    ap.add_argument("--min-salary-n", type=int, default=3, help="min employer-stated salaries per state x role cell")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or OUT_DIR / f"job_market_scorecard_{datetime.now():%Y%m%d}.xlsx"

    data = read_gold(get_engine())
    build_workbook(out, data, top_n=args.top_skills, min_salary_n=args.min_salary_n)

    latest = out.parent / "job_market_scorecard_latest.xlsx"
    shutil.copyfile(out, latest)
    print(f"Excel export written: {out}")
    print(f"  jobs={len(data['jobs'])} skills_links={len(data['skills'])} -> also copied to {latest.name}")


if __name__ == "__main__":
    main()
