"""Налаштування системи: шляхи, ліміти джерел, параметри моделі.

Усі значення зібрані в одному місці, щоб жодне обмеження не було
захардкоджене всередині інструментів.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- шляхи ---------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "Data"
INPUT_DIR = DATA_DIR / "Input"
REFERENCE_DIR = DATA_DIR / "Reference"
OUTPUT_DIR = DATA_DIR / "Output"
PLANS_DIR = DATA_DIR / "plans"
CACHE_PATH = PROJECT_ROOT / "cache.sqlite"

# --- мережа --------------------------------------------------------------

USER_AGENT = "ExcelEnrichment/1.0 (Neoversity study project; contact via GitHub)"
HTTP_TIMEOUT = 10  # секунд на один запит
HTTP_RETRIES = 3
HTTP_BACKOFF = (1, 2, 4)  # паузи між спробами, секунд

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
WIKIDATA_BATCH_SIZE = 50  # сутностей в одному SPARQL-запиті

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_MIN_INTERVAL = 1.0  # секунда між запитами, вимога OSM

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
OSRM_MIN_INTERVAL = 1.0  # публічний демо-сервер, не розпаралелювати

# --- модель --------------------------------------------------------------

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-5.6-luna")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Ціни за мільйон токенів, потрібні лише для оцінки вартості у звіті.
LLM_PRICE_INPUT = float(os.getenv("LLM_PRICE_INPUT", "0.0"))
LLM_PRICE_OUTPUT = float(os.getenv("LLM_PRICE_OUTPUT", "0.0"))

# --- виконання -----------------------------------------------------------

MAX_WORKERS = 8  # потоків на рядки
MAX_TOOL_ATTEMPTS = 2  # спроб різними інструментами на один рядок
DISAGREEMENT_THRESHOLD = 0.10  # 10 відсотків розбіжності між джерелами

EARTH_RADIUS_KM = 6371.0088  # середній радіус, стандарт IUGG
