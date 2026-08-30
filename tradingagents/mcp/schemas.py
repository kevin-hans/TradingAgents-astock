"""MCP 工具入参 pydantic schemas。

CLAUDE.md 薄壳方针：本文件只 import 第三方 (pydantic) + 标准库 (typing)，
不 import advisor/graph/dataflows/agents/performance 等业务模块。
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class KYCAnswersIn(BaseModel):
    """薄壳：MCP 层不解释答案语义（value/序号/带圈都透传），归一化住 CLI。"""

    q1: int | str = Field(description="选项 value (3/5/7/9)；序号 1-4 或 ①-④ 亦可，服务端归一化")
    q2: int | str = Field(description="选项 value (3/5/7/9)；序号 1-4 或 ①-④ 亦可，服务端归一化")
    q3: int | str = Field(description="选项 value (3/5/7/9)；序号 1-4 或 ①-④ 亦可，服务端归一化")
    q4: int | str = Field(description="选项 value (3/5/7/9)；序号 1-4 或 ①-④ 亦可，服务端归一化")
    q5: int | str = Field(description="选项 value (3/5/7/9)；序号 1-4 或 ①-④ 亦可，服务端归一化")
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
