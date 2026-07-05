"""Candidate company slugs for discovery.

These are lowercase name-slugs probed against Greenhouse/Lever/Ashby. Only slugs
whose board actually returns jobs get registered, so this list can be liberal:
wrong guesses are simply ignored. Extend it freely to widen coverage.
"""

_RAW: list[str] = [
    # --- Fintech / payments ---
    "stripe", "brex", "ramp", "mercury", "plaid", "affirm", "chime", "sofi",
    "wealthfront", "betterment", "robinhood", "gemini", "coinbase", "circle",
    "moderntreasury", "unit", "checkr", "marqeta", "bill", "carta", "addepar",
    # --- Dev tools / infra ---
    "gitlab", "hashicorp", "cloudflare", "digitalocean", "vercel", "netlify",
    "render", "supabase", "posthog", "sentry", "launchdarkly", "retool", "hex",
    "replit", "cockroachlabs", "temporal", "grafanalabs", "pulumi", "fivetran",
    "airbyte", "dbtlabs", "materialize", "planetscale", "neon", "railway",
    # --- AI / ML ---
    "openai", "anthropic", "scale", "huggingface", "runway", "cohere", "adept",
    "perplexityai", "together", "mistral", "weightsandbiases", "labelbox",
    "cursor", "anysphere", "harvey", "glean", "sierra", "writer",
    # --- Productivity / SaaS ---
    "notion", "linear", "figma", "airtable", "asana", "miro", "loom", "calendly",
    "grammarly", "canva", "clickup", "monday", "coda", "zapier", "webflow",
    "amplitude", "mixpanel", "segment", "productboard", "pendo", "gong",
    # --- Marketplaces / consumer ---
    "airbnb", "instacart", "doordash", "lyft", "pinterest", "reddit", "discord",
    "patreon", "faire", "thumbtack", "nextdoor", "opendoor", "compass", "gopuff",
    "kickstarter", "eventbrite", "turo", "rover", "getaround", "hipcamp",
    # --- Data / security / enterprise ---
    "databricks", "snowflake", "samsara", "benchling", "flexport", "gusto",
    "rippling", "deel", "remote", "justworks", "lattice", "verkada", "envoy",
    "vanta", "drata", "wiz", "snyk", "abnormalsecurity", "1password", "tailscale",
    # --- Health / bio / climate ---
    "watershed", "clay", "ro", "cityblock", "devoted", "hims", "colorhealth",
    "commure", "included", "maven", "spring",
    # --- Education / media ---
    "coursera", "udemy", "duolingo", "quizlet", "chegg", "medium", "substack",
    "quora", "brilliant",
    # --- More fintech / crypto ---
    "stubhub", "gusto", "current", "varo", "dave", "mxtechnologies", "alloy",
    "petal", "tala", "nerdwallet", "creditkarma", "kraken", "blockchain",
    "paxos", "fireblocks", "chainalysis", "alchemy", "ledger",
    # --- More dev tools / infra / security ---
    "docker", "circleci", "sourcegraph", "gradle", "jfrog", "sonarsource",
    "postman", "kong", "grafana", "chronosphere", "honeycomb", "datadog",
    "sysdig", "aquasecurity", "orca", "semgrep", "socket", "doppler",
    "cloudsmith", "warp", "zed", "modal", "baseten", "fal", "e2b",
    # --- More AI / data ---
    "elevenlabs", "assemblyai", "deepgram", "pinecone", "weaviate", "chroma",
    "llamaindex", "langchain", "contextual", "mistralai", "suno", "captions",
    "descript", "synthesia", "tome", "gamma", "browserbase",
    # --- More SaaS / product / ops ---
    "ramp", "rippling", "deel", "airbase", "brex", "mercury", "pilot", "puzzle",
    "float", "ashby", "greenhouse", "lever", "gem", "rippling", "assembled",
    "front", "intercom", "zendesk", "twilio", "sendbird", "courier",
    "knock", "customerio", "attentive", "iterable", "braze", "hightouch",
    "census", "rudderstack", "metabase", "preset", "count", "omni",
    # --- More consumer / marketplace / health ---
    "whoop", "oura", "levels", "function", "transcarent", "hims",
    "noom", "cerebral", "headway", "grow", "sondermind", "brightside",
    "alma", "zocdoc", "cedar", "olive", "garner",
]

# De-duplicate while preserving order so the list can be edited liberally.
CANDIDATE_SLUGS: list[str] = list(dict.fromkeys(_RAW))
