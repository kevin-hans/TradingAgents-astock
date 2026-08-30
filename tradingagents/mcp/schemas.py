"""MCP 工具入参 pydantic schemas。

CLAUDE.md 薄壳方针：本文件只 import 第三方 (pydantic) + 标准库 (typing)，
不 import advisor/graph/dataflows/agents/performance 等业务模块。
"""
from typing import Literal, Optional

from pydantic import BaseModel


class KYCAnswersIn(BaseModel):
    q1: Literal[3, 5, 7, 9]
    q2: Literal[3, 5, 7, 9]
    q3: Literal[3, 5, 7, 9]
    q4: Literal[3, 5, 7, 9]
    q5: Literal[3, 5, 7, 9]
    schema_version: Literal[1] = 1


class ReportsArgs(BaseModel):
    ticker: Optional[str] = None


class ScenarioArgs(BaseModel):
    ticker: str
    date: Optional[str] = None


class AdviseArgs(BaseModel):
    ticker: str
    kyc_answers: Optional[KYCAnswersIn] = None
    date: Optional[str] = None


class ReviewArgs(BaseModel):
    kyc_answers: Optional[KYCAnswersIn] = None


class AnalyzeArgs(BaseModel):
    ticker: str
    depth: Literal["quick", "analyst", "full"] = "full"
    confirm: bool = False
    single_analyst: Optional[str] = None
    force: bool = False
