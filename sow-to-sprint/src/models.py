from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class Clause(BaseModel):
    """One numbered/lettered chunk of the SOW, with a stable id we can cite."""
    id: str
    section: str
    text: str


class ScopeItem(BaseModel):
    id: str
    title: str
    description: str
    function: Literal["technical", "commercial", "operations", "design"]
    module: str | None = None
    quantity: int | None = None
    unit: str | None = None
    source_clause_id: str
    source_excerpt: str
    confidence: Literal["high", "medium", "low"]


class Milestone(BaseModel):
    id: str
    name: str
    due_date: date
    linked_scope_item_ids: list[str] = Field(default_factory=list)


class SOWExtraction(BaseModel):
    sow_id: str
    version: int
    client_name: str
    project_name: str
    signature_date: date | None = None
    delivery_date: date
    modules: list[str] = Field(default_factory=list)
    scope_items: list[ScopeItem] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    milestones: list[Milestone] = Field(default_factory=list)
    slas: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    commercial_targets: list[ScopeItem] = Field(default_factory=list)
    unmapped_clauses: list[str] = Field(default_factory=list)


Phase = Literal["Discovery", "Build", "UAT", "Launch", "Post-launch"]

WorkItemType = Literal[
    "epic",
    "user_story",
    "test_case",
    "tech_validation",
    "commercial_task",
    "ops_task",
    "design_task",
    "milestone",
]


class WorkItem(BaseModel):
    id: str
    parent_id: str | None = None
    type: WorkItemType
    function: Literal["technical", "commercial", "operations", "design"]
    title: str
    description: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    gherkin: str | None = None
    squad: str | None = None
    assignee: str | None = None
    estimate_days: float
    depends_on: list[str] = Field(default_factory=list)
    phase: Phase
    start_date: date | None = None
    due_date: date | None = None
    source_clause_id: str
    source_excerpt: str
    confidence: Literal["high", "medium", "low"]
    status: Literal["generated", "approved", "rejected", "edited"] = "generated"


class SyncRecord(BaseModel):
    work_item_id: str
    trello_board_id: str
    trello_list_id: str
    trello_card_id: str
    content_hash: str
    synced_at: datetime