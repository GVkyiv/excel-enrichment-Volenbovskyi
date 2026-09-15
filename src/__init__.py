"""Система інтелектуального збагачення Excel-даних.

Публічна точка входу одна: `process_excel`. Решта модулів це шари, які
вона збирає (читання книги, планувальник, інструменти, граф, запис).
"""

from .models import EnrichmentPlan, EnrichmentReport, RowResult
from .pipeline import process_excel

__all__ = ["process_excel", "EnrichmentPlan", "EnrichmentReport", "RowResult"]
__version__ = "0.1.0"
