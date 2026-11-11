"""Stable public error codes and their Uzbek messages. No internal detail leaks."""

from __future__ import annotations

ERRORS: dict[str, tuple[int, str]] = {
    "invalid_request": (422, "So‘rov noto‘g‘ri. Savolni 3–600 belgi oralig‘ida yozing."),
    "rate_limited": (429, "Juda ko‘p so‘rov yuborildi. Birozdan keyin qayta urinib ko‘ring."),
    "daily_limit": (429, "Bugungi so‘rovlar limiti tugadi. Ertaga qayta urinib ko‘ring."),
    "busy": (503, "Hozir tizim band. Bir necha soniyadan keyin qayta urinib ko‘ring."),
    "budget_exhausted": (503, "Demo uchun bugungi AI limiti tugadi. Manba sahifalari ishlashda davom etadi."),
    "generation_unavailable": (503, "Javob berish vaqtincha o‘chirilgan. Hujjatlar ro‘yxati ishlayapti."),
    "corpus_unavailable": (503, "Indekslangan hujjatlar hozircha mavjud emas."),
    "provider_timeout": (504, "AI xizmati o‘z vaqtida javob bermadi. Qayta urinib ko‘ring."),
    "provider_rate_limited": (503, "AI xizmati hozir cheklangan. Birozdan keyin urinib ko‘ring."),
    "provider_quota": (
        503,
        "Bepul AI kvotasi hozircha tugagan (daqiqalik yoki kunlik limit). Birozdan keyin yoki ertaga qayta "
        "urinib ko‘ring. Hujjatlar ro‘yxati ishlashda davom etadi.",
    ),
    "quota_exhausted": (
        503,
        "Demo uchun AI so‘rovlari limiti hozircha tugagan (bepul kvota). Keyinroq qayta urinib ko‘ring.",
    ),
    "provider_unavailable": (503, "AI xizmati vaqtincha ishlamayapti."),
    "provider_auth": (503, "AI xizmati sozlanmagan."),
    "provider_bad_request": (502, "AI xizmati so‘rovni qabul qilmadi."),
    "not_found": (404, "Topilmadi."),
    "internal_error": (500, "Ichki xatolik yuz berdi."),
}


def error_payload(code: str, request_id: str) -> tuple[int, dict]:
    status, message = ERRORS.get(code, ERRORS["internal_error"])
    if code not in ERRORS:
        code = "internal_error"
    return status, {"request_id": request_id, "error": {"code": code, "message": message}}
