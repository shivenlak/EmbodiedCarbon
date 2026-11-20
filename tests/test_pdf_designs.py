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


def _pdf(path, pages):
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        doc.new_page(width=600, height=400).insert_text((50, 200), text, fontsize=12)
    doc.save(path)


def test_a_folder_of_files_is_one_design(tmp_path):
    """Builders deliver one set as several PDFs: one design, one page index."""
    from ecarbon.config import folder_design, source_of

    _pdf(tmp_path / "Floor Layout.pdf", ["plan one", "plan two"])
    _pdf(tmp_path / "Mech & Electrical.pdf", ["ducts"])

    d = folder_design(tmp_path)

    assert d.key == tmp_path.name
    assert source_of(d.drawings_pdf, 0) == ("Floor Layout.pdf", 0)
    assert source_of(d.drawings_pdf, 2) == ("Mech & Electrical.pdf", 0)
    assert source_of(d.drawings_pdf, 3) is None
    # The joined copy is not itself a design.
    assert [x.key for x in pdf_designs(tmp_path)] == ["Floor Layout", "Mech & Electrical"]


def test_a_folder_of_one_file_is_that_file(tmp_path):
    from ecarbon.config import folder_design, source_of

    _pdf(tmp_path / "Set.pdf", ["x"])
    d = folder_design(tmp_path)
    assert d.drawings_pdf == tmp_path / "Set.pdf"
    assert source_of(d.drawings_pdf, 0) is None


def test_the_file_name_types_a_page_the_title_block_could_not(tmp_path):
    from ecarbon.config import folder_design
    from ecarbon.intake.inventory import inventory
    from ecarbon.models import BasisSource, SheetType

    _pdf(tmp_path / "Floor Layout.pdf", ["no title block here"])
    _pdf(tmp_path / "Mech & Electrical.pdf", ["ducts"])
    _pdf(tmp_path / "Final Blueprint.pdf", ["says nothing"])

    sheets, _, _ = inventory(folder_design(tmp_path).drawings_pdf)

    # Joined in name order: Final Blueprint, Floor Layout, Mech & Electrical.
    assert [s.sheet_type for s in sheets] == [
        SheetType.UNKNOWN,  # "Final Blueprint" names no type: not guessed
        SheetType.FRAMING_PLAN,
        SheetType.MECHANICAL,
    ]
    assert sheets[1].classified_by is BasisSource.DEFAULT_RULE
    assert sheets[1].title.endswith("(from file name)")


def test_file_name_types():
    from ecarbon.intake.classify import type_from_file_name
    from ecarbon.models import SheetType

    assert type_from_file_name("Roof Layout.pdf") is SheetType.FRAMING_PLAN
    assert type_from_file_name("Floor Layout.pdf") is SheetType.FRAMING_PLAN
    assert type_from_file_name("Foundation.pdf") is SheetType.FOUNDATION_PLAN
    assert type_from_file_name("Building Details.pdf") is SheetType.DETAIL
    assert type_from_file_name("Mech & Electrical.pdf") is SheetType.MECHANICAL
    assert type_from_file_name("Final Blueprint.pdf") is SheetType.UNKNOWN
