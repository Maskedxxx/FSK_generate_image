"""
Тест guard-роутера на полном датасете: 5 валидных + 9 невалидных кейсов.

Использует упрощённый OSMI-флоу с одним guard + Условие + 2 Прямых ответа.
Полный пайплайн НЕ запускается — экономия кредитов.

python osmi_nodes/tests/test_guard_dataset.py
"""

import base64
import json
import time
from pathlib import Path

import requests

GUARD_URL = "https://app.osmi-ai.ru/api/v1/prediction/726f5642-5039-431d-94b3-4032031cf4b6"
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "guard"


def call_guard(image_path: Path) -> dict:
    """Отправляет картинку в guard-флоу. Возвращает распарсенный JSON ответ."""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    question = f"{b64}|||{{}}"
    r = requests.post(GUARD_URL, json={"question": question}, timeout=60)
    if r.status_code != 200:
        return {"_error": f"HTTP {r.status_code}", "_text": r.text[:200]}
    body = r.json()
    text = body.get("text", "")
    try:
        return json.loads(text) if isinstance(text, str) else text
    except Exception:
        return {"_error": "JSON parse failed", "_text": text[:300]}


def run_case(image_path: Path, expected_valid: bool) -> dict:
    """Прогоняет один кейс. Возвращает результат с детальной инфой."""
    t0 = time.monotonic()
    result = call_guard(image_path)
    dt = round(time.monotonic() - t0, 1)

    if "_error" in result:
        return {
            "name": image_path.name,
            "expected": "valid" if expected_valid else "invalid",
            "actual": "ERROR",
            "passed": False,
            "duration": dt,
            "error": result.get("_error"),
            "raw": result.get("_text", ""),
        }

    actual_valid = result.get("is_valid", "").lower() == "true"
    passed = actual_valid == expected_valid

    return {
        "name": image_path.name,
        "expected": "valid" if expected_valid else "invalid",
        "actual": "valid" if actual_valid else "invalid",
        "passed": passed,
        "duration": dt,
        "image_type": result.get("image_type", ""),
        "confidence": result.get("confidence", 0),
        "threats": result.get("threats", []),
        "reasoning": result.get("reasoning", []),
    }


def print_row(r: dict):
    icon = "✅" if r["passed"] else "❌"
    name = r["name"][:40].ljust(40)
    expected = r["expected"].ljust(7)
    actual = r["actual"].ljust(7)
    threats_str = ",".join(r.get("threats", []))[:30]
    print(f"  {icon} {name} | exp={expected} | got={actual} | {r['duration']}s | {threats_str}")


def main():
    print("=" * 100)
    print("  Guard-роутер: полный датасет тестов")
    print(f"  URL: {GUARD_URL}")
    print("=" * 100)

    results = []

    # Валидные
    valid_dir = FIXTURES_DIR / "valid"
    valid_files = sorted(valid_dir.glob("*.jpg")) + sorted(valid_dir.glob("*.png"))
    print(f"\n📋 Валидные ({len(valid_files)} кейсов) — ожидаем is_valid=true:\n")
    for img_path in valid_files:
        r = run_case(img_path, expected_valid=True)
        results.append(r)
        print_row(r)

    # Невалидные
    invalid_dir = FIXTURES_DIR / "invalid"
    invalid_files = sorted(invalid_dir.glob("*.jpg")) + sorted(invalid_dir.glob("*.png"))
    print(f"\n📋 Невалидные ({len(invalid_files)} кейсов) — ожидаем is_valid=false:\n")
    for img_path in invalid_files:
        r = run_case(img_path, expected_valid=False)
        results.append(r)
        print_row(r)

    # Итог
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    total = len(results)
    total_time = sum(r["duration"] for r in results)

    print("\n" + "=" * 100)
    print(f"  Результат: {passed}/{total} пройдено ({failed} провалено), общее время {round(total_time, 1)}s")
    print("=" * 100)

    # Детали по проваленным
    if failed:
        print("\n❌ Детали по проваленным кейсам:\n")
        for r in results:
            if r["passed"]:
                continue
            print(f"\n  📁 {r['name']} (ожидали {r['expected']}, получили {r['actual']})")
            if "error" in r:
                print(f"     Ошибка: {r['error']}")
                print(f"     Ответ: {r.get('raw', '')[:200]}")
                continue
            print(f"     image_type: {r.get('image_type', '')}")
            print(f"     confidence: {r.get('confidence', '')}")
            print(f"     threats: {r.get('threats', [])}")
            print("     reasoning:")
            for step in r.get("reasoning", []):
                print(f"       - {step[:120]}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
