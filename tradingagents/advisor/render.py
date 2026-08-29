"""3×3 矩阵采样 + 人类可读渲染。

铁律：矩阵每一格 == 引擎对该 (γ, H_avail) 直算，不做插值/平滑。
"""
from typing import Literal

from pydantic import BaseModel

from tradingagents.advisor.engine import advise
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import ScenarioBucket


# γ 预设：保守 / 中性 / 激进（数值降序）
MATRIX_GAMMA_PRESETS: tuple[float, float, float] = (8.0, 5.0, 2.5)
# H_avail 预设（月）：短线 / 中线 / 长线（升序）
MATRIX_HORIZON_PRESETS: tuple[int, int, int] = (3, 24, 120)


class MatrixCell(BaseModel):
    gamma_eff: float
    h_avail_months: float
    weight_star: float
    action: Literal["avoid", "observe", "hold_underweight", "increase_overweight"]


class MatrixRow(BaseModel):
    gamma_label: str
    cells: list[MatrixCell]


class Matrix(BaseModel):
    horizon_labels: list[str]
    rows: list[MatrixRow]


def sample_matrix_cell(
    bucket: ScenarioBucket,
    config: AdvisorConfig,
    gamma_eff: float,
    h_avail_months: int,
) -> MatrixCell:
    vec = InvestorVector(gamma_eff=gamma_eff, hc=1.0, h_avail_months=float(h_avail_months))
    r = advise(bucket, vec, config)
    return MatrixCell(
        gamma_eff=gamma_eff,
        h_avail_months=float(h_avail_months),
        weight_star=r.trace.w_star,
        action=r.with_position.action,
    )


def render_matrix(bucket: ScenarioBucket, config: AdvisorConfig) -> Matrix:
    gamma_labels = ["保守", "中性", "激进"]
    horizon_labels = [
        f"短线 {MATRIX_HORIZON_PRESETS[0]}月",
        f"中线 {MATRIX_HORIZON_PRESETS[1]}月",
        f"长线 {MATRIX_HORIZON_PRESETS[2]}月",
    ]
    rows: list[MatrixRow] = []
    for gi, gamma in enumerate(MATRIX_GAMMA_PRESETS):
        cells = [
            sample_matrix_cell(bucket, config, gamma, h)
            for h in MATRIX_HORIZON_PRESETS
        ]
        rows.append(MatrixRow(gamma_label=gamma_labels[gi], cells=cells))
    return Matrix(horizon_labels=horizon_labels, rows=rows)


def render_text(matrix: Matrix, highlighted: tuple[int, int] | None = None) -> str:
    """把矩阵渲染成 ASCII 表格。highlighted=(row_idx, col_idx) 加星号。"""
    lines = [
        "                " + "  ".join(f"{h:>12}" for h in matrix.horizon_labels)
    ]
    for gi, row in enumerate(matrix.rows):
        cell_texts = []
        for ci, cell in enumerate(row.cells):
            marker = "*" if highlighted == (gi, ci) else " "
            cell_texts.append(
                f"{marker}{cell.action:<20}[w*={cell.weight_star:.1%}]"
            )
        lines.append(f"γ={row.gamma_label:<4}  " + "  ".join(cell_texts))
    return "\n".join(lines)
