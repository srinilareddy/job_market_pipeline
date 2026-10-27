# Building the Power BI report

Files: `powerbi/queries.pq` (Power Query) and `powerbi/measures.dax` (model, columns, measures).
Estimated time: 60-90 minutes the first time.

**Platform note:** Power BI Desktop runs on Windows only. On a Mac use a Windows VM, a Windows PC,
or build in a cloud Windows machine. The Excel scorecard (`output/excel/`) works on any platform.

## 1. Connect to the database
- Docker stack: on the Windows machine, tunnel the port first
  (`ssh -L 5433:localhost:5433 you@your-server`), then the server is `localhost:5433`.
- Local Postgres: server `<mac-ip>:5432` (Postgres must accept network connections).
- If Desktop asks for the **Npgsql** provider, install it (Power BI links to it).
- Use a **read-only** database user for the report, not the pipeline's owner account.

## 2. Load the three tables
1. Home > Transform data > Manage Parameters: create text parameters `pgServer` and `pgDatabase`.
2. New blank queries from `queries.pq` sections **1, 2, 3** only, named exactly `Jobs`, `JobSkills`,
   `PipelineRuns` (sections 4-5 are Excel-only). Close & Apply (Import mode).

## 3. Model
1. Create `DimDate` (DAX file, section 1). Mark it as the date table on `DimDate[Date]`. Set
   `DimDate[Month]` to sort by `Month Sort`.
2. Relationships, all single direction, one side first:
   `DimDate[Date] 1 -> * Jobs[posting_date]`, `Jobs[job_pk] 1 -> * JobSkills[job_pk]`.
   `PipelineRuns` has no relationship.
3. Add the 5 calculated columns to `Jobs` (section 2) and set `Salary Band` to sort by `Salary Band Sort`.
4. Add the measures (sections 3-8). Group them into display folders as the comments suggest.

## 4. Reconcile before you build visuals
Run the two queries at the bottom of `measures.dax` in **DAX query view**. Compare with the Excel
scorecard and `docs/metrics.sql`. They must agree on total jobs, unique companies, jobs with salary
and median salary. If not, fix the model (data types, relationships) before going further.

## 5. Pages (suggested layout)

**Page 1 - Market overview**
- Cards: `Total Jobs`, `Jobs Last 7 Days` (subtitle: `WoW Label`, font colour from `WoW Color`),
  `Unique Companies`, `Median Salary` with `Jobs With Salary` beside it, `Top Skill`.
- Line chart: `DimDate[Date]` x `Jobs 7-Day Avg` (and `Total Jobs` as columns).
- Bar chart: `Jobs[role_family]` x `Total Jobs`.
- Table: role family, `Total Jobs`, `Jobs With Salary`, `Median Salary`, `P25 Salary`, `P75 Salary`.
- Slicers: `role_family`, `Seniority`, `Salary Source`.

**Page 2 - Skills**
- Bar chart: `JobSkills[skill_name]` x `Jobs With Skill`, filtered to Top 15 by `Jobs With Skill`.
- Matrix: rows `skill_name`, columns `Jobs[role_family]`, values `Skill Demand %`, heat-map formatting.

**Page 3 - Pipeline health**
- Cards: `Data Freshness` (font colour from `Freshness Color`), `Last Successful Run`, `Pipeline Success Rate`.
- Column chart: `PipelineRuns[run_ts]` x `jobs_added`; table of `PipelineRuns`.

Use the native **KPI** visual with Value `[Jobs Last 7 Days]`, Target `[Jobs Prior 7 Days]`,
Trend axis `DimDate[Week Start]`.

## 6. Keep the report honest (put these in a text box on page 1)
- Salary figures are **employer-stated salaries only** (Adzuna's estimates are excluded) and
  rest on a small share of postings: always show `Jobs With Salary` next to a salary number.
- Skills are detected in Adzuna's ~500-character description snippet, so percentages understate
  real requirements; use them to compare skills with each other, not as absolute demand.
- Role family is a title-keyword heuristic, and role proportions reflect which searches the
  pipeline runs, not the market's true mix.

## 7. Refreshing
Desktop: Home > Refresh. For scheduled refresh in the Power BI service, a local or tunnelled
Postgres needs an on-premises data gateway. Without one, export screenshots (or a PDF) after each
refresh for the repository and share the `.pbix` only if it contains no credentials.
