from __future__ import annotations

from pathlib import Path


def main() -> None:
    # ReportLab is already available in many Python environments; if not,
    # install it with: pip install reportlab
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    out_dir = Path("data/docs")
    out_dir.mkdir(parents=True, exist_ok=True)

    def make(path: Path, title: str, platform: str) -> None:
        c = canvas.Canvas(str(path), pagesize=letter)
        w, h = letter
        y = h - 72
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, y, title)
        y -= 28
        c.setFont("Helvetica", 12)
        lines = [
            "This is a dummy placeholder PDF for development/testing.",
            "Replace this file with the real branded onboarding document.",
            "",
            f"Platform: {platform}",
            "",
            "Steps:",
            "1) Go through the doc and follow the steps",
            "2) Set the correct settings in your account",
            "3) Deposit at least $100 in your account",
            "4) Return to the Welcome channel and click Continue",
        ]
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
        c.save()

    make(out_dir / "premier_onboarding.pdf", "Fusion Wealth - Premier Onboarding (Dummy)", "Premier")
    make(out_dir / "vantage_onboarding.pdf", "Fusion Wealth - Vantage Onboarding (Dummy)", "Vantage")

    def make_ct(path: Path, title: str, platform: str) -> None:
        c = canvas.Canvas(str(path), pagesize=letter)
        w, h = letter
        y = h - 72
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, y, title)
        y -= 28
        c.setFont("Helvetica", 12)
        lines = [
            "Dummy copy-trading setup guide (replace with branded PDF).",
            "",
            f"Platform: {platform}",
            "",
            "1) Go through the doc and follow the steps",
            "2) Set the correct settings in your account",
            "3) Deposit at least $500 in your account",
            "4) When done click continue",
        ]
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
        c.save()

    make_ct(out_dir / "premier_copytrading.pdf", "Fusion Wealth - Premier Copy Trading (Dummy)", "Premier")
    make_ct(out_dir / "vantage_copytrading.pdf", "Fusion Wealth - Vantage Copy Trading (Dummy)", "Vantage")

    def make_ob(path: Path, title: str, platform: str) -> None:
        c = canvas.Canvas(str(path), pagesize=letter)
        w, h = letter
        y = h - 72
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, y, title)
        y -= 28
        c.setFont("Helvetica", 12)
        lines = [
            "Dummy offboard / detach guide (replace with branded PDF).",
            "",
            f"Platform: {platform}",
            "",
            "Follow these steps to detach from Fusion Wealth in your platform.",
        ]
        for line in lines:
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
        c.save()

    make_ob(out_dir / "premier_offboard.pdf", "Fusion Wealth - Premier Offboard (Dummy)", "Premier")
    make_ob(out_dir / "vantage_offboard.pdf", "Fusion Wealth - Vantage Offboard (Dummy)", "Vantage")

    print("Created:")
    print(" -", out_dir / "premier_onboarding.pdf")
    print(" -", out_dir / "vantage_onboarding.pdf")
    print(" -", out_dir / "premier_copytrading.pdf")
    print(" -", out_dir / "vantage_copytrading.pdf")
    print(" -", out_dir / "premier_offboard.pdf")
    print(" -", out_dir / "vantage_offboard.pdf")


if __name__ == "__main__":
    main()

