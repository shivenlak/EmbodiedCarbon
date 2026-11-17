"""Unseen sets (Landmark's) arrive as loose PDFs, not catalogue packages."""

from ecarbon.config import pdf_designs


def test_every_pdf_in_a_folder_is_a_design(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("Model A.pdf", "sub/Model B.pdf", "_sidecar.pdf", "notes.txt"):
        (tmp_path / name).write_bytes(b"%PDF-1.7")

    designs = pdf_designs(tmp_path)

    assert [d.key for d in designs] == ["Model A", "Model B"]
    assert all(d.ifc is None and not d.bpr for d in designs)


def test_a_single_pdf_is_one_design(tmp_path):
    pdf = tmp_path / "Set.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    assert [d.drawings_pdf for d in pdf_designs(pdf)] == [pdf]
