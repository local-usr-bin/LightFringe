"""Explanatory text only. Never changes physical predictions."""
from fractions import Fraction


def missing_order_relation(width_um: int, separation_um: int) -> tuple[int, int]:
    """Use exact integer-micrometre GUI inputs, never a float approximation.

    If d/a = p/q in lowest terms, every p-th interference maximum coincides
    with an envelope minimum of order q. This is an ideal far-field statement.
    """
    if type(width_um) is not int or type(separation_um) is not int:
        raise ValueError("缺级关系只接受 GUI 的精确整数微米输入")
    if not 0 < width_um < separation_um:
        raise ValueError("无效双缝几何")
    ratio = Fraction(separation_um, width_um)
    return ratio.numerator, ratio.denominator


def missing_order_note(width_um: int, separation_um: int) -> str:
    p, q = missing_order_relation(width_um, separation_um)
    ratio = str(p) if q == 1 else f"{p}/{q}"
    return f"d/a = {ratio}；每第 {p} 级理论缺级（理想远场）"
