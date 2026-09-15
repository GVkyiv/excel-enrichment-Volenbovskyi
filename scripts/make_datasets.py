"""Генератор допоміжних наборів: ломалка і стрес-тест.

`broken.xlsx` навмисно містить усі випадки, які система має пережити без
аварії. `stress_1000.xlsx` це тисяча пар столиць для заміру масштабованості.
"""

from __future__ import annotations

import random
from itertools import combinations
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "Data" / "Input"

# Назви столиць рівно в тому вигляді, як вони підписані в Wikidata.
CAPITALS = [
    ("Kyiv", "Ukraine"), ("Paris", "France"), ("Berlin", "Germany"),
    ("Rome", "Italy"), ("Madrid", "Spain"), ("Lisbon", "Portugal"),
    ("Vienna", "Austria"), ("Budapest", "Hungary"), ("Warsaw", "Poland"),
    ("Prague", "Czech Republic"), ("Bratislava", "Slovakia"),
    ("Ljubljana", "Slovenia"), ("Zagreb", "Croatia"), ("Belgrade", "Serbia"),
    ("Sarajevo", "Bosnia and Herzegovina"), ("Skopje", "North Macedonia"),
    ("Sofia", "Bulgaria"), ("Bucharest", "Romania"), ("Chisinau", "Moldova"),
    ("Athens", "Greece"), ("Ankara", "Turkey"), ("Nicosia", "Cyprus"),
    ("Valletta", "Malta"), ("Tirana", "Albania"), ("Podgorica", "Montenegro"),
    ("Stockholm", "Sweden"), ("Oslo", "Norway"), ("Helsinki", "Finland"),
    ("Copenhagen", "Denmark"), ("Reykjavik", "Iceland"), ("Tallinn", "Estonia"),
    ("Riga", "Latvia"), ("Vilnius", "Lithuania"), ("Minsk", "Belarus"),
    ("Moscow", "Russia"), ("Dublin", "Ireland"), ("Amsterdam", "Netherlands"),
    ("Brussels", "Belgium"), ("Luxembourg", "Luxembourg"), ("Bern", "Switzerland"),
    ("Monaco", "Monaco"), ("Andorra la Vella", "Andorra"), ("Cairo", "Egypt"),
    ("Tunis", "Tunisia"), ("Algiers", "Algeria"), ("Rabat", "Morocco"),
    ("Tripoli", "Libya"), ("Nairobi", "Kenya"), ("Addis Ababa", "Ethiopia"),
    ("Pretoria", "South Africa"), ("Abuja", "Nigeria"), ("Accra", "Ghana"),
    ("Dakar", "Senegal"), ("Tehran", "Iran"), ("Baghdad", "Iraq"),
    ("Riyadh", "Saudi Arabia"), ("Doha", "Qatar"), ("Amman", "Jordan"),
    ("Beirut", "Lebanon"), ("Damascus", "Syria"), ("Jerusalem", "Israel"),
    ("Tbilisi", "Georgia"), ("Yerevan", "Armenia"), ("Baku", "Azerbaijan"),
    ("Astana", "Kazakhstan"), ("Tashkent", "Uzbekistan"), ("Bishkek", "Kyrgyzstan"),
    ("Kabul", "Afghanistan"), ("Islamabad", "Pakistan"), ("New Delhi", "India"),
    ("Kathmandu", "Nepal"), ("Dhaka", "Bangladesh"), ("Colombo", "Sri Lanka"),
    ("Bangkok", "Thailand"), ("Hanoi", "Vietnam"), ("Phnom Penh", "Cambodia"),
    ("Vientiane", "Laos"), ("Kuala Lumpur", "Malaysia"), ("Singapore", "Singapore"),
    ("Jakarta", "Indonesia"), ("Manila", "Philippines"), ("Tokyo", "Japan"),
    ("Seoul", "South Korea"), ("Beijing", "China"), ("Ulaanbaatar", "Mongolia"),
    ("Canberra", "Australia"), ("Wellington", "New Zealand"), ("Ottawa", "Canada"),
    ("Mexico City", "Mexico"), ("Havana", "Cuba"), ("Bogota", "Colombia"),
    ("Lima", "Peru"), ("Santiago", "Chile"), ("Buenos Aires", "Argentina"),
    ("Montevideo", "Uruguay"), ("Asuncion", "Paraguay"), ("La Paz", "Bolivia"),
    ("Quito", "Ecuador"), ("Caracas", "Venezuela"), ("Brasilia", "Brazil"),
]


def make_broken() -> Path:
    """Набір, у якому кожен рядок ламає систему по-своєму."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Mountain", "Country", "height"])
    rows = [
        ("Mount Everest", "Nepal/China", None),        # контроль: має заповнитись
        ("Atlantis", "Nowhere", None),                 # сутності не існує
        (None, "Nepal", None),                         # порожня вхідна комірка
        ("K2", "Pakistan/China", 8000),                # вже заповнено, не чіпаємо
        ("Olympus Mons", "Mars", None),                # значення поза межами
        ("Qwerty Nonexistent Peak", "Nowhere", None),  # сміття замість назви
    ]
    for row in rows:
        sheet.append(row)
    path = INPUT_DIR / "broken.xlsx"
    workbook.save(path)
    return path


def make_stress(rows: int = 1000, seed: int = 42) -> Path:
    """Тисяча пар столиць для заміру масштабованості."""
    random.seed(seed)
    pairs = list(combinations(range(len(CAPITALS)), 2))
    random.shuffle(pairs)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["Capital_From", "Country_From", "Capital_To", "Country_To", "distance"]
    )
    for first, second in pairs[:rows]:
        sheet.append([*CAPITALS[first], *CAPITALS[second], None])
    path = INPUT_DIR / f"stress_{rows}.xlsx"
    workbook.save(path)
    return path


if __name__ == "__main__":
    print("Створено:", make_broken())
    print("Створено:", make_stress())
