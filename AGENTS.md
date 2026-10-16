PROJECT: Hybrid fraud detection for Indian welfare-scheme data (synthetic): rule engine + IsolationForest + LangGraph agents + FastAPI + Streamlit.
STACK: Python 3.11+, pandas, numpy, scikit-learn, fpdf2, Faker, FastAPI, Streamlit, LangGraph, pytest. LLM via an OpenAI-compatible client; base URL and key from env (LLM_BASE_URL, LLM_API_KEY, LLM_MODEL). If no key is set, agents must run in deterministic OFFLINE mode (templates), so everything works without internet.
WORKFLOW: work in small steps; read only files named in the task; never rewrite a working file wholesale, use targeted edits; no long explanations in replies (max 10 lines summary); run tests after each change; do not commit secrets or data/ output.
LAYOUT TARGET: src/fraud/{config.py,simulate.py,rules/,ml.py,graph.py,pipeline.py,evaluate.py,agents/,notice.py,api.py}, app/dashboard.py, tests/, reports/, configs/default.yaml, Dockerfile, Makefile.
HONESTY: every metric in docs must come from reports/metrics.json produced by `make eval`. Never invent or hand-edit numbers. Say "synthetic data" wherever results appear.
STYLE: type hints, small functions, thresholds in configs/default.yaml, all randomness seeded (default seed 42), pathlib paths, logging not print.
DONE MEANS: `make test` and `make eval` pass.
