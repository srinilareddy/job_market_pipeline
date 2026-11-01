"""
HYBRID NLP + Reference Database Skill Extraction
Combines automatic NLP discovery with known skills validation for best accuracy.

This is the BEST approach because:
1. Automatically discovers new skills (like pure NLP)
2. Validates against known categories (like database)
3. Minimal maintenance (only update categories, not individual skills)
4. High accuracy with low noise
"""
import re
from typing import List, Set, Dict
from collections import defaultdict, Counter

# ============================================================================
# SKILL CATEGORIES - Easy to maintain, covers broad areas
# ============================================================================

# Programming Languages & Scripts
PROGRAMMING_LANGUAGES = {
    "python", "java", "javascript", "typescript", "c++", "c#", "c", "go", 
    "rust", "scala", "ruby", "php", "swift", "kotlin", "r", "sql", "bash", 
    "shell", "powershell", "perl", "lua", "dart", "elixir", "haskell", 
    "clojure", "julia", "groovy", "objective-c", "vb.net", "fortran", "cobol"
}

# Web Frameworks & Libraries
WEB_FRAMEWORKS = {
    "react", "angular", "vue", "svelte", "next.js", "nuxt", "gatsby",
    "django", "flask", "fastapi", "spring", "spring boot", "express", 
    "node.js", "nestjs", "laravel", "rails", "asp.net", "blazor",
    "jquery", "bootstrap", "tailwind"
}

# Data Science & ML
ML_DATA_SCIENCE = {
    "tensorflow", "pytorch", "keras", "scikit-learn", "xgboost", "lightgbm",
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly",
    "jupyter", "mlflow", "kubeflow", "sagemaker", "vertex ai",
    "machine learning", "deep learning", "neural networks", "nlp",
    "natural language processing", "computer vision", "reinforcement learning"
}

# Big Data & Streaming
BIG_DATA = {
    "spark", "pyspark", "hadoop", "hive", "presto", "flink", "storm",
    "kafka", "kinesis", "pub/sub", "dataflow", "beam", "nifi"
}

# Databases
DATABASES = {
    "postgresql", "mysql", "mariadb", "sql server", "oracle", "db2",
    "mongodb", "cassandra", "couchbase", "dynamodb", "cosmosdb",
    "redis", "memcached", "elasticsearch", "solr", "neo4j", "arangodb",
    "snowflake", "bigquery", "redshift", "athena", "databricks",
    "clickhouse", "timescaledb", "influxdb"
}

# Cloud Platforms & Services
CLOUD_PLATFORMS = {
    "aws", "azure", "gcp", "google cloud", "amazon web services", 
    "microsoft azure", "cloud computing", "alibaba cloud", "oracle cloud",
    "s3", "ec2", "lambda", "rds", "cloudfront", "route53",
    "azure functions", "azure devops", "cloud storage", "compute engine"
}

# DevOps & Infrastructure
DEVOPS_INFRASTRUCTURE = {
    "docker", "kubernetes", "k8s", "terraform", "ansible", "puppet", "chef",
    "jenkins", "gitlab ci", "github actions", "circleci", "travis ci",
    "ci/cd", "devops", "argo", "helm", "istio", "prometheus", "grafana",
    "nagios", "datadog", "new relic", "splunk", "elk", "linux", "unix",
    "windows", "nginx", "tomcat"
}

# Data Tools & BI
DATA_BI_TOOLS = {
    "tableau", "power bi", "looker", "qlik", "metabase", "superset",
    "excel", "google sheets", "alteryx", "talend", "informatica",
    "airflow", "prefect", "dagster", "luigi", "dbt", "fivetran"
}

# Version Control & Collaboration
VERSION_CONTROL = {
    "git", "github", "gitlab", "bitbucket", "svn", "mercurial",
    "jira", "confluence", "slack", "teams"
}

# Testing & QA
TESTING_QA = {
    "selenium", "cypress", "jest", "pytest", "junit", "testng",
    "cucumber", "postman", "jmeter", "loadrunner", "qa", "tdd", "bdd"
}

# Methodologies & Concepts
METHODOLOGIES = {
    "agile", "scrum", "kanban", "waterfall", "devops", "ci/cd",
    "microservices", "rest", "rest api", "graphql", "grpc", "soap",
    "etl", "elt", "data pipeline", "data warehouse", "data lake",
    "api", "sdk", "oauth", "jwt", "ssl", "tls"
}

# Statistics, Analytics & Modeling
# Added after a rebuild showed an earlier version of the extractor tracked these and the hybrid
# dictionary did not. Deliberately EXCLUDED as too generic or ambiguous: "data analysis" and
# "data engineering" (job-title words), "regression" (regression testing), "classification"
# (job classification), "optimization", "mathematics". Prune this list to taste.
STATS_ANALYTICS = {
    "statistics", "statistical analysis", "statistical modeling", "hypothesis testing", "a/b testing",
    "time series", "predictive modeling", "data modeling", "data visualization", "data warehousing",
    "data mining", "data structures", "algorithms", "quicksight", "spss", "sas", "stata"
}

# Combine all known skills
ALL_KNOWN_SKILLS = (
    PROGRAMMING_LANGUAGES | WEB_FRAMEWORKS | ML_DATA_SCIENCE | BIG_DATA |
    DATABASES | CLOUD_PLATFORMS | DEVOPS_INFRASTRUCTURE | DATA_BI_TOOLS |
    VERSION_CONTROL | TESTING_QA | METHODOLOGIES | STATS_ANALYTICS
)

# ============================================================================
# AMBIGUOUS SKILL NAMES - also ordinary English words / non-skills.
# Matching these case-insensitively inflates counts ("Go to market", "Teams",
# "Spring season"). They only count when written Capitalised AND used in a
# skill-list context: after a comma/slash/paren/bullet, or after
# with/in/using/and/or/of.  e.g. "Python, Go, and SQL" -> yes, "Go to market" -> no.
# ============================================================================
AMBIGUOUS_SKILLS = {
    "go", "r", "c", "swift", "ruby", "spring", "express", "storm", "beam",
    "chef", "puppet", "teams", "windows", "rest",
}
_CONTEXT_PREFIX = r"(?:[,/(;\u2022\-]|\b(?:with|in|using|and|or|of)\b)\s*"

# Words that, right after the skill, show it is ordinary English ("Go Fast", "Go Live", "Go to market").
_BLOCKED_NEXT_WORD = {"go": r"to|fast|live|big|above|beyond|further|forward|ahead|getter|green"}

def _ambiguous_match(skill: str, text: str) -> bool:
    cap = re.escape(skill.capitalize() if len(skill) > 1 else skill.upper())
    # trailing "&" rejects "R&R", "R&D", "C&I"; "(?!\.\w)" rejects "R.js"-style tokens
    tail = r"(?![\w+#&-])(?!\.\w)"
    block = _BLOCKED_NEXT_WORD.get(skill)
    if block:
        tail += rf"(?!\s+(?i:{block})\b)"
    # (?<!HVAC) rejects "HVAC/R" (refrigeration), which otherwise reads like "...slash R"
    return re.search(r"(?<!HVAC)" + _CONTEXT_PREFIX + cap + tail, text) is not None


# "excel" is also a verb ("you should excel in..."). The software is virtually always written
# capitalised, so match only "Excel"/"EXCEL", and not when followed by in/at/under/as/by.
_CASE_SENSITIVE_SKILLS = {
    "excel": r"(?<![\w])(?:Excel|EXCEL)(?![\w])(?!\s+(?i:in|at|under|as|by)\b)",
}

# Different spellings of one skill are merged so counts are not split or double-counted.
SKILL_ALIASES = {
    "amazon web services": "aws",
    "google cloud": "gcp",
    "microsoft azure": "azure",
    "natural language processing": "nlp",
    "k8s": "kubernetes",
    "rest api": "rest",
}

# ============================================================================
# EXCLUSIONS - Things that are definitely NOT skills
# ============================================================================

EXCLUDE_WORDS = {
    # Common words
    "experience", "knowledge", "ability", "strong", "excellent", "required",
    "preferred", "years", "work", "team", "project", "company", "candidate",
    "position", "role", "responsibilities", "qualifications", "overview",
    "description", "summary", "location", "remote", "hybrid", "onsite",
    
    # Job posting metadata
    "req", "id", "number", "ref", "responsibilities", "position",
    
    # Generic tech words (too broad)
    "data", "technology", "software", "hardware", "systems", "platform",
    "cloud", "web", "mobile", "desktop", "server", "client",
    
    # Locations & Companies (add as needed)
    "ca", "ny", "tx", "fl", "usa", "us", "nc", "wwt",
}

# ============================================================================
# HYBRID EXTRACTOR
# ============================================================================

class HybridSkillExtractor:
    """
    Hybrid approach: Uses NLP patterns to discover skills, 
    then validates against known categories.
    """
    
    def __init__(self, strict_mode: bool = True):
        """
        Initialize extractor.
        
        Args:
            strict_mode: If True, only return skills in known categories.
                        If False, also include high-confidence unknown skills.
        """
        self.strict_mode = strict_mode
        self.known_skills_lower = {s.lower() for s in ALL_KNOWN_SKILLS}
    
    def _normalize(self, text: str) -> str:
        """Normalize skill name."""
        return re.sub(r'\s+', ' ', text.lower().strip())
    
    def _extract_candidates(self, text: str) -> Set[str]:
        """Extract potential skills using NLP patterns."""
        candidates = set()
        text_lower = text.lower()
        
        # 1. Exact matches from known skills
        for skill in ALL_KNOWN_SKILLS:
            if skill in _CASE_SENSITIVE_SKILLS:
                if re.search(_CASE_SENSITIVE_SKILLS[skill], text):
                    candidates.add(skill)
                continue
            if skill in AMBIGUOUS_SKILLS:
                if _ambiguous_match(skill, text):
                    candidates.add(skill)
                continue
            pattern = r'(?<![\w])' + re.escape(skill) + r'(?![\w])'
            if re.search(pattern, text_lower):
                candidates.add(skill)
        
        # 2. CamelCase terms (e.g., JavaScript, PyTorch)
        camel_case = re.findall(r'\b[A-Z][a-z]*(?:[A-Z][a-z]*)+\b', text)
        candidates.update(camel_case)
        
        # 3. Uppercase acronyms (e.g., AWS, SQL, API)
        acronyms = re.findall(r'\b[A-Z]{2,}(?:/[A-Z]{2,})?\b', text)
        candidates.update(acronyms)
        
        # 4. Dotted notation (e.g., Node.js, d3.js)
        dotted = re.findall(r'\b[A-Za-z]+\.[A-Za-z]+\b', text)
        candidates.update(dotted)
        
        # 5. Hyphenated tech terms (e.g., scikit-learn)
        hyphenated = re.findall(r'\b[a-z]+(?:-[a-z]+)+\b', text_lower)
        candidates.update(hyphenated)
        
        return candidates
    
    def _is_valid_skill(self, candidate: str) -> bool:
        """Check if candidate is a valid skill."""
        candidate_lower = self._normalize(candidate)
        
        # Exclude known non-skills
        if candidate_lower in EXCLUDE_WORDS:
            return False
        
        # In strict mode, must be in known skills
        if self.strict_mode:
            return candidate_lower in self.known_skills_lower
        
        # In lenient mode, check patterns
        # Must be CamelCase, UPPERCASE, dotted, or hyphenated
        if (re.match(r'^[A-Z][a-z]*(?:[A-Z][a-z]*)+$', candidate) or  # CamelCase
            re.match(r'^[A-Z]{2,}$', candidate) or                      # UPPERCASE
            '.' in candidate or '-' in candidate):                      # dotted/hyphenated
            return True
        
        return False
    
    def extract_skills(self, text: str) -> List[str]:
        """
        Extract skills from text.
        
        Args:
            text: Job description
            
        Returns:
            List of validated skills
        """
        if not text or not isinstance(text, str):
            return []
        
        # Extract candidates using NLP
        candidates = self._extract_candidates(text)
        
        # Validate candidates
        valid_skills = {
            SKILL_ALIASES.get(self._normalize(skill), self._normalize(skill))
            for skill in candidates
            if self._is_valid_skill(skill)
        }
        
        return sorted(list(valid_skills))
    
    def extract_skills_batch(self, texts: List[str]) -> Dict[str, int]:
        """Extract skills from multiple texts with frequency counts."""
        all_skills = Counter()
        
        for text in texts:
            skills = self.extract_skills(text)
            all_skills.update(skills)
        
        return dict(all_skills)


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

_extractor = None

def get_skill_extractor(strict_mode: bool = True) -> HybridSkillExtractor:
    """Get singleton extractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = HybridSkillExtractor(strict_mode=strict_mode)
    return _extractor


def extract_skills(text: str, strict_mode: bool = True) -> List[str]:
    """
    Extract skills from text using hybrid approach.
    
    Args:
        text: Job description
        strict_mode: If True, only return known skills
        
    Returns:
        List of skills
    """
    extractor = get_skill_extractor(strict_mode=strict_mode)
    return extractor.extract_skills(text)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    sample_texts = [
        """
        Senior Data Scientist position requires 5+ years experience with Python, R, 
        and SQL. Must have strong knowledge of machine learning, deep learning, and NLP.
        Experience with TensorFlow, PyTorch, and scikit-learn required. 
        Cloud experience with AWS (SageMaker, S3, EC2) preferred.
        """,
        """
        Full Stack Developer needed. Required skills: JavaScript, TypeScript, React.js, 
        Node.js, and MongoDB. Experience with CI/CD, Docker, Kubernetes, and AWS.
        Knowledge of GraphQL, REST APIs, and microservices architecture is a plus.
        """,
        """
        DevOps Engineer role. Must know: Linux, Bash scripting, Terraform, Ansible,
        Jenkins, GitLab CI, GitHub Actions. Strong experience with AWS, Azure, or GCP.
        Docker and Kubernetes expertise required.
        """
    ]
    
    print("=" * 70)
    print("🎯 HYBRID NLP + REFERENCE DATABASE EXTRACTION")
    print("=" * 70)
    
    extractor = HybridSkillExtractor(strict_mode=True)
    
    for i, text in enumerate(sample_texts, 1):
        print(f"\n📝 Job Description #{i}:")
        print("-" * 70)
        
        skills = extractor.extract_skills(text)
        print(f"\n✅ Found {len(skills)} validated skills:")
        for skill in skills:
            print(f"   • {skill}")
    
    # Batch analysis
    print("\n" + "=" * 70)
    print("📊 BATCH ANALYSIS")
    print("=" * 70)
    
    skill_freq = extractor.extract_skills_batch(sample_texts)
    sorted_skills = sorted(skill_freq.items(), key=lambda x: x[1], reverse=True)
    
    print(f"\n🔝 Most Common Skills:")
    for skill, count in sorted_skills[:20]:
        bar = "█" * (count * 3)
        print(f"   {skill:30} {bar} {count}")
    
    print(f"\n📈 Total unique skills: {len(skill_freq)}")
