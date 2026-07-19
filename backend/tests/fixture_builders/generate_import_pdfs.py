"""Gera PDFs anonimizados usados pela regressao dos importadores.

Execute a partir de backend/: python tests/fixture_builders/generate_import_pdfs.py
"""
from pathlib import Path

from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def write_pdf(name: str, lines: list[str]) -> None:
    target = ROOT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target))
    pdf.setFont("Helvetica", 9)
    y = 800
    for line in lines:
        pdf.drawString(40, y, line)
        y -= 18
    pdf.save()


write_pdf("santander_statement.pdf", [
    "SANTANDER EXTRATO CONSOLIDADO CONTA CORRENTE MARCO / 2026",
    "SALDO EM 28/02 1.000,00",
    "01/03 PIX RECEBIDO CLIENTE TESTE 500,00",
    "02/03 PIX ENVIADO FORNECEDOR TESTE 125,50-",
    "03/03 TARIFA PACOTE 10,00-",
    "SALDO EM 31/03 1.364,50",
])

write_pdf("nubank_statement.pdf", [
    "NUBANK Extrato de 01/03/2026 a 31/03/2026",
    "Saldo inicial R$ 100,00",
    "Rendimento liquido R$ 0,00",
    "Saldo final do periodo R$ 250,00",
    "Movimentacoes",
    "05 MAR 2026",
    "Transferencia recebida por Pix +200,00",
    "06 MAR 2026",
    "Compra no debito MERCADO TESTE -50,00",
    "Tem alguma duvida?",
])

write_pdf("nubank_empty_statement.pdf", [
    "NUBANK Extrato janeiro / 2024",
    "Saldo inicial R$ 0,00",
    "Movimentacoes",
    "Nenhuma movimentacao",
    "Saldo final do periodo R$ 0,00",
])

card_lines = [
    "SANTANDER DETALHAMENTO DA FATURA",
    "Vencimento 10/04/2026",
]
for day in range(1, 13):
    card_lines.append(f"{day:02d}/03 LOJA TESTE {day:02d}/12 {day * 10},00")
write_pdf("santander_card.pdf", card_lines)
