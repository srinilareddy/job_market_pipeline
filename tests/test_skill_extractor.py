"""Run: python -m pytest tests/ -q   (from project root)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "transform"))
from skill_extractor_hybrid import extract_skills  # noqa: E402

AMBIGUOUS = {"go", "teams", "spring", "r", "c"}


def _check(text, expected):
    got = set(extract_skills(text))
    assert set(expected) <= got, f"missing {set(expected) - got}"
    assert not (AMBIGUOUS & got) - set(expected), f"false positive in {got}"


def test_go_the_word_is_not_go_the_language():
    _check("Go to market mindset and team player", [])
    _check("Go above and beyond. Go live in Q4.", [])


def test_go_in_a_skill_list_counts():
    _check("Proficiency in Python, Go, and SQL", ["go", "python", "sql"])


def test_teams_and_spring_are_not_skills_in_prose():
    _check("Work with cross-functional teams in a spring season", [])


def test_symbol_languages():
    _check("Knowledge of C++, C#, R and Java", ["c#", "c++", "java", "r"])


def test_stats_and_analytics_skills_recognised():
    _check("Experience with statistics, time series, A/B testing and data visualization",
           ["statistics", "time series", "a/b testing", "data visualization"])
    _check("Build dashboards in QuickSight or SPSS; data modeling and data warehousing", 
           ["quicksight", "spss", "data modeling", "data warehousing"])


def test_generic_phrases_are_not_skills():
    got = set(extract_skills("Job classification, regression testing, data analysis and optimization of data engineering"))
    assert not ({"classification", "regression", "data analysis", "optimization", "data engineering"} & got), got


def test_company_values_and_abbreviations_are_not_skills():
    _check("Our values: Be Bold, Go Fast, Collaborate, and Celebrate", [])
    _check("the new construction and Repair & Remodel (R&R) markets and R&D teams", [])


def test_real_short_skill_mentions_still_found():
    _check("Rust and Go in the open on GitHub", ["go"])
    _check("tools such as Python, R, Snowflake, SQL", ["r", "python", "snowflake", "sql"])
    _check("program in C++, C, and Python", ["c", "c++", "python"])
    _check("Unity/C# and Go. You will be responsible", ["go", "c#"])
    _check("Node.js & Golang/Go experience", ["go"])


def test_excel_the_verb_is_not_excel_the_software():
    _check("You should excel in working with large-scale applications", [])
    _check("Candidates who excel at communication", [])
    got = set(extract_skills("Proficiency in Microsoft Excel, SQL and Word, Excel and PowerPoint"))
    assert "excel" in got, got


def test_apache_is_a_prefix_not_a_skill():
    got = set(extract_skills("Apache Airflow DAGs and Apache Spark jobs"))
    assert {"airflow", "spark"} <= got and "apache" not in got, got


def test_hvac_r_is_not_the_r_language():
    _check("America's largest HVAC/R service provider", [])
    _check("Python, R, and SQL", ["python", "r", "sql"])


def test_aliases_are_merged():
    got = set(extract_skills("Amazon Web Services (AWS), Google Cloud, Microsoft Azure and Natural Language Processing (NLP)"))
    assert {"aws", "gcp", "azure", "nlp"} <= got, got
    assert not ({"amazon web services", "google cloud", "microsoft azure", "natural language processing"} & got), got
