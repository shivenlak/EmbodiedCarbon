

def test_sk_mb_foundation_framing_plan_is_the_foundation_plan():
    from ecarbon.intake.classify import sheet_type_of
    from ecarbon.models import SheetType

    assert sheet_type_of("FOUNDATION / FRAMING PLAN") is SheetType.FOUNDATION_PLAN
