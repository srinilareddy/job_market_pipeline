// =====================================================================
//  POWER QUERY (M) - works in Power BI Desktop AND Excel (Data > Get Data
//  > From Other Sources > Blank Query > Advanced Editor).
//  Create one query per section below. Server/database are parameters so
//  the same file works on any machine.
// =====================================================================


// ---------------------------------------------------------------------
// 0) Parameters  (Home > Manage Parameters > New Parameter, type = Text)
//    pgServer   = localhost:5432
//    pgDatabase = job_market
//    (Power BI Desktop prompts for DB credentials on first load: choose
//     "Database" and enter the read-only user. Never hardcode a password in M.)
// ---------------------------------------------------------------------


// ---------------------------------------------------------------------
// 1) Jobs   <- gold.fct_jobs
// ---------------------------------------------------------------------
let
    Source   = PostgreSQL.Database(pgServer, pgDatabase),
    Gold     = Source{[Schema = "gold", Item = "fct_jobs"]}[Data],
    Typed    = Table.TransformColumnTypes(Gold, {
                   {"job_pk", Int64.Type}, {"posting_date", type date},
                   {"created_at", type datetime},
                   {"salary_min", type number}, {"salary_max", type number}, {"salary_avg", type number},
                   {"salary_est_avg", type number}, {"salary_basis", type text},
                   {"has_salary", type logical}, {"skill_count", Int64.Type},
                   {"title", type text}, {"role_family", type text}, {"company_name", type text},
                   {"state_name", type text}, {"location_name", type text},
                   {"contract_time", type text}, {"redirect_url", type text}}),
    // Empty strings from the pipeline -> null so DAX BLANK() logic works
    Cleaned  = Table.ReplaceValue(
                   Table.ReplaceValue(Typed, "", null, Replacer.ReplaceValue, {"contract_time", "contract_type"}),
                   "NaN", null, Replacer.ReplaceValue, {"contract_time", "contract_type"}),
    Keep     = Table.RemoveColumns(Cleaned, {"source_job_id"}, MissingField.Ignore)
in
    Keep


// ---------------------------------------------------------------------
// 2) JobSkills   <- gold.fct_job_skills   (bridge: one row per job x skill)
//    role_family is dropped on purpose: filter by Jobs[role_family] only,
//    otherwise two role fields exist and the model is ambiguous.
// ---------------------------------------------------------------------
let
    Source = PostgreSQL.Database(pgServer, pgDatabase),
    Gold   = Source{[Schema = "gold", Item = "fct_job_skills"]}[Data],
    Keep   = Table.SelectColumns(Gold, {"job_pk", "skill_name"}),
    Typed  = Table.TransformColumnTypes(Keep, {{"job_pk", Int64.Type}, {"skill_name", type text}})
in
    Typed


// ---------------------------------------------------------------------
// 3) PipelineRuns   <- ops.pipeline_runs
//    run_ts is converted to UTC so DAX UTCNOW() comparisons are correct
//    in both Desktop and the Power BI service.
// ---------------------------------------------------------------------
let
    Source = PostgreSQL.Database(pgServer, pgDatabase),
    Ops    = Source{[Schema = "ops", Item = "pipeline_runs"]}[Data],
    UTC    = Table.TransformColumns(Ops, {{"run_ts",
                 each if _ = null then null
                      else DateTime.From(DateTimeZone.RemoveZone(DateTimeZone.SwitchZone(_, 0))),
                 type datetime}}),
    Typed  = Table.TransformColumnTypes(UTC, {
                 {"raw_records", Int64.Type}, {"jobs_total", Int64.Type}, {"jobs_added", Int64.Type},
                 {"companies", Int64.Type}, {"skills", Int64.Type}, {"skill_links", Int64.Type},
                 {"status", type text}, {"run_id", type text}})
in
    Typed


// ---------------------------------------------------------------------
// 4) EXCEL ONLY: a refreshable summary table straight from Postgres
//    (Excel: Data > Get Data > From Database > PostgreSQL, then paste this
//     in the Advanced Editor.  Load To > Table, then Insert > PivotTable
//     on the loaded table -> a native, refreshable PivotTable.)
// ---------------------------------------------------------------------
let
    Source   = PostgreSQL.Database(pgServer, pgDatabase),
    Skills   = Source{[Schema = "gold", Item = "skill_demand_by_role"]}[Data],
    Typed    = Table.TransformColumnTypes(Skills, {{"job_count", Int64.Type}, {"pct_of_role_jobs", type number}}),
    Filtered = Table.SelectRows(Typed, each [job_count] >= 3),            // drop one-off noise
    Sorted   = Table.Sort(Filtered, {{"role_family", Order.Ascending}, {"job_count", Order.Descending}})
in
    Sorted


// ---------------------------------------------------------------------
// 5) EXCEL ONLY: append the pipeline's own export (the .xlsx the DAG writes)
//    Shows Power Query's file connector + type handling. Point the path at
//    output/excel/job_market_scorecard_latest.xlsx
// ---------------------------------------------------------------------
let
    Source = Excel.Workbook(File.Contents("C:\path\to\output\excel\job_market_scorecard_latest.xlsx"), null, true),
    Jobs   = Source{[Item = "tblJobs", Kind = "Table"]}[Data],
    Typed  = Table.TransformColumnTypes(Jobs, {{"posting_date", type date}, {"salary_avg", type number}}),
    ByRole = Table.Group(Typed, {"role_family"}, {
                 {"Jobs",       each Table.RowCount(_), Int64.Type},
                 {"Avg Salary", each List.Average(List.RemoveNulls([salary_avg])), type nullable number}})
in
    ByRole
