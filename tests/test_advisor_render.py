import pytest

from tradingagents.advisor.engine import advise
from tradingagents.advisor.render import (
    render_matrix,
    render_text,
    sample_matrix_cell,
    MATRIX_GAMMA_PRESETS,
    MATRIX_HORIZON_PRESETS,
)
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket


def _bucket() -> ScenarioBucket:
    return ScenarioBucket(
        horizon_months=6,
        scenarios=[
            Scenario(name="bull", thesis="...", expected_return=0.25, prob=0.35),
            Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
            Scenario(name="bear", thesis="...", expected_return=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=8.5, entry_low=9.5, entry_high=10.5, target=12.5),
    )


class TestMatrixEqEngine:
    """铁律：矩阵 3×3 每一格 == 引擎对该 (γ, horizon) 直算。"""

    def test_all_nine_cells_match_engine(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        matrix = render_matrix(bucket, cfg)

        assert len(matrix.rows) == 3
        for row in matrix.rows:
            assert len(row.cells) == 3
        for gi, gamma in enumerate(MATRIX_GAMMA_PRESETS):
            for hi, horizon in enumerate(MATRIX_HORIZON_PRESETS):
                cell = matrix.rows[gi].cells[hi]
                vec = InvestorVector(
                    gamma_eff=gamma, hc=1.0, h_avail_months=float(horizon),
                )
                expected = advise(bucket, vec, cfg)
                assert cell.weight_star == pytest.approx(expected.trace.w_star)
                assert cell.action == expected.with_position.action


class TestSingleCell:
    def test_sample_matrix_cell_matches_engine(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        gamma = MATRIX_GAMMA_PRESETS[1]
        horizon = MATRIX_HORIZON_PRESETS[1]
        cell = sample_matrix_cell(bucket, cfg, gamma, horizon)
        vec = InvestorVector(gamma_eff=gamma, hc=1.0, h_avail_months=float(horizon))
        expected = advise(bucket, vec, cfg)
        assert cell.weight_star == pytest.approx(expected.trace.w_star)


class TestTextRender:
    def test_text_render_contains_key_fields(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        matrix = render_matrix(bucket, cfg)
        text = render_text(matrix, highlighted=(1, 1))

        assert "γ" in text
        assert "月" in text  # horizon label contains "月"
        # 至少每个 cell 的 action 或 weight 出现在 text 里
        for row in matrix.rows:
            for cell in row.cells:
                assert cell.action in text or f"{cell.weight_star:.1%}" in text


class TestPresets:
    def test_gamma_presets_length_3(self):
        assert len(MATRIX_GAMMA_PRESETS) == 3

    def test_horizon_presets_length_3(self):
        assert len(MATRIX_HORIZON_PRESETS) == 3

    def test_gamma_presets_conservative_to_aggressive(self):
        """conservative (high γ) > neutral > aggressive (low γ)"""
        assert MATRIX_GAMMA_PRESETS[0] > MATRIX_GAMMA_PRESETS[1] > MATRIX_GAMMA_PRESETS[2]

    def test_horizon_presets_short_to_long(self):
        assert MATRIX_HORIZON_PRESETS[0] < MATRIX_HORIZON_PRESETS[1] < MATRIX_HORIZON_PRESETS[2]
