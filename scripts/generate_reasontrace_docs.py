"""Generate five visibly fictional, one-page ReasonTrace document packets.

Run with a Python that has Pillow installed. No names or financial data come from users.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "reasontrace"
ROOT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def document(filename: str, eyebrow: str, title: str, rows: list[tuple[str, str]], note: str):
    image = Image.new("RGB", (1400, 1650), "#faf9f6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 1330, 1580), fill="#ffffff", outline="#cbd1d8", width=3)
    draw.rectangle((70, 70, 1330, 86), fill="#162b40")
    draw.text((120, 135), eyebrow.upper(), fill="#52718a", font=font(27, True))
    draw.text((120, 185), title, fill="#14293d", font=font(62, True))
    draw.line((120, 300, 1280, 300), fill="#cbd1d8", width=3)
    draw.text((120, 340), "Applicant: Alex Morgan (fictional)", fill="#34495b", font=font(31))
    draw.text((120, 395), "Case: RT-SYN-001  |  Issued: 2026-09-30", fill="#34495b", font=font(28))
    y = 510
    for label, value in rows:
        draw.rectangle((115, y - 10, 1285, y + 94), fill="#f2f5f7" if (y // 130) % 2 else "#fff")
        draw.text((130, y + 10), label, fill="#4b6173", font=font(30))
        draw.text((785, y + 8), value, fill="#132b40", font=font(34, True))
        y += 132
    draw.line((120, 1370, 1280, 1370), fill="#cbd1d8", width=3)
    draw.text((120, 1410), note, fill="#465d70", font=font(25))
    draw.text((120, 1510), "SYNTHETIC TEST DOCUMENT  •  NOT A REAL BORROWER OR CREDIT REPORT", fill="#a04a44", font=font(21, True))
    image.save(ROOT / filename, optimize=True)


document(
    "pay-stub.png",
    "Northstar Goods — payroll demonstration",
    "Pay statement",
    [
        ("Employee", "Alex Morgan"),
        ("Pay period", "September 2026"),
        ("Gross monthly pay", "$5,000.00"),
        ("Annualized gross pay", "$60,000.00"),
        ("Net deposited", "$4,120.00"),
    ],
    "Annual income for this test case is the annualized gross amount above.",
)
document(
    "bank-statement.png",
    "Harbor Bank — fictional account",
    "Bank statement",
    [
        ("Account holder", "Alex Morgan"),
        ("Account ending", "•• 0482"),
        ("Statement period", "Sep 1–30, 2026"),
        ("Payroll deposit", "$4,120.00"),
        ("Ending balance", "$7,840.00"),
    ],
    "The deposit is net pay; it is not substituted for annual gross income.",
)
document(
    "credit-report.png",
    "Meridian test bureau — synthetic record",
    "Credit summary",
    [
        ("Consumer", "Alex Morgan"),
        ("Report date", "September 30, 2026"),
        ("Credit score", "635"),
        ("Monthly debt payments", "$600.00"),
        ("Open tradelines", "6"),
    ],
    "For interview evaluation only. This is not a real bureau report.",
)


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def packet_document(case: dict, filename: str, eyebrow: str, title: str,
                    rows: list[tuple[str, str]], note: str) -> None:
    """Render later packets without changing the original case's saved bytes."""
    image = Image.new("RGB", (1400, 1650), "#faf9f6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 1330, 1580), fill="#ffffff", outline="#cbd1d8", width=3)
    draw.rectangle((70, 70, 1330, 86), fill="#162b40")
    draw.text((120, 135), eyebrow.upper(), fill="#52718a", font=font(27, True))
    draw.text((120, 185), title, fill="#14293d", font=font(62, True))
    draw.line((120, 300, 1280, 300), fill="#cbd1d8", width=3)
    draw.text((120, 340), f"Applicant: {case['applicantName']} (fictional)", fill="#34495b", font=font(31))
    draw.text((120, 395), f"Case: {case['label']}  |  Issued: 2026-09-30", fill="#34495b", font=font(28))
    y = 510
    for label, value in rows:
        draw.rectangle((115, y - 10, 1285, y + 94), fill="#f2f5f7" if (y // 130) % 2 else "#fff")
        draw.text((130, y + 10), label, fill="#4b6173", font=font(30))
        draw.text((785, y + 8), value, fill="#132b40", font=font(34, True))
        y += 132
    draw.line((120, 1370, 1280, 1370), fill="#cbd1d8", width=3)
    draw.text((120, 1410), note, fill="#465d70", font=font(25))
    draw.text((120, 1510), "SYNTHETIC TEST DOCUMENT  •  NOT A REAL BORROWER OR CREDIT REPORT", fill="#a04a44", font=font(21, True))
    destination = ROOT / case["label"]
    destination.mkdir(exist_ok=True)
    image.save(destination / filename, optimize=True)


manifest = json.loads((ROOT.parents[1] / "web/lib/reasontrace/cases.json").read_text())
for case in manifest[1:]:
    packet_document(
        case, "pay-stub.png", f"{case['employer']} — fictional payroll", "Pay statement",
        [
            ("Employee", case["applicantName"]),
            ("Pay period", "September 2026"),
            ("Gross monthly pay", money(case["annualIncomeCents"] // 12)),
            ("Annualized gross pay", money(case["annualIncomeCents"])),
            ("Net deposited", money(case["netMonthlyCents"])),
        ],
        "Income is the annualized gross amount, not the net deposit.",
    )
    packet_document(
        case, "bank-statement.png", f"{case['bank']} — fictional account", "Bank statement",
        [
            ("Account holder", case["applicantName"]),
            ("Account ending", f"•• {case['accountLast4']}"),
            ("Statement period", "Sep 1–30, 2026"),
            ("Payroll deposit", money(case["netMonthlyCents"])),
            ("Ending balance", money(case["bankEndingBalanceCents"])),
        ],
        "The deposit is net pay; it is not substituted for gross income.",
    )
    packet_document(
        case, "credit-report.png", "Meridian test bureau — synthetic record", "Credit summary",
        [
            ("Consumer", case["applicantName"]),
            ("Report date", "September 30, 2026"),
            ("Credit score", str(case["creditScore"])),
            ("Monthly debt payments", money(case["monthlyDebtCents"])),
            ("Open tradelines", "6"),
        ],
        "For interview evaluation only. This is not a real bureau report.",
    )
