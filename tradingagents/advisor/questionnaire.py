from typing import Literal

from pydantic import BaseModel


class KYCOption(BaseModel):
    label: str
    value: Literal[3, 5, 7, 9]


class KYCQuestion(BaseModel):
    id: Literal["q1", "q2", "q3", "q4", "q5"]
    text: str
    options: list[KYCOption]


class Questionnaire(BaseModel):
    schema_version: Literal[1] = 1
    questions: list[KYCQuestion]
    note: str = (
        "客户端本地存 KYC 原始答案，每次调用 advise/review 时 inline 传给服务端。"
        "服务端负责校准（γ_eff / HC / H_avail 公式住 advisor/calibrate.py）。"
    )


_QUESTIONS: list[KYCQuestion] = [
    KYCQuestion(id="q1", text="如果你的组合浮亏 20%，你的第一反应是？", options=[
        KYCOption(label="全部卖出", value=3),
        KYCOption(label="卖一部分", value=5),
        KYCOption(label="持有", value=7),
        KYCOption(label="加仓", value=9),
    ]),
    KYCQuestion(id="q2", text="这笔钱多久内可能被动用？", options=[
        KYCOption(label="6 个月内", value=3),
        KYCOption(label="6-24 个月", value=5),
        KYCOption(label="2-5 年", value=7),
        KYCOption(label="5 年以上", value=9),
    ]),
    KYCQuestion(id="q3", text="你的权益类投资经验？", options=[
        KYCOption(label="无", value=3),
        KYCOption(label="仅基金", value=5),
        KYCOption(label="个股", value=7),
        KYCOption(label="含衍生品", value=9),
    ]),
    KYCQuestion(id="q4", text="你的收入稳定性？", options=[
        KYCOption(label="不稳定", value=3),
        KYCOption(label="一般", value=5),
        KYCOption(label="稳定", value=7),
        KYCOption(label="高且上升", value=9),
    ]),
    KYCQuestion(id="q5", text="你的年龄段？", options=[
        KYCOption(label="60 岁以上", value=3),
        KYCOption(label="45-59 岁", value=5),
        KYCOption(label="30-44 岁", value=7),
        KYCOption(label="30 岁以下", value=9),
    ]),
]


KYC_Q2_MONTHS: dict[int, int] = {3: 3, 5: 15, 7: 42, 9: 120}
KYC_Q4_INCOME_STABILITY: dict[int, float] = {3: 0.3, 5: 0.5, 7: 0.8, 9: 1.0}
KYC_Q5_AGE: dict[int, int] = {3: 65, 5: 52, 7: 37, 9: 25}


def get_questionnaire() -> Questionnaire:
    return Questionnaire(questions=_QUESTIONS)
