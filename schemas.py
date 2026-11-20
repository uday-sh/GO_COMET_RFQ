from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class UserRole(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"


class TransportMode(StrEnum):
    ROAD = "road"
    AIR = "air"
    OCEAN = "ocean"
    RAIL = "rail"
    MULTIMODAL = "multimodal"
    COURIER = "courier"


class FreightService(StrEnum):
    FTL = "ftl"
    LTL = "ltl"
    FCL = "fcl"
    LCL = "lcl"
    REEFER = "reefer"
    HAZMAT = "hazmat"
    OVERSIZED = "oversized"
    EXPRESS = "express"
    CUSTOMS = "customs"
    WAREHOUSING = "warehousing"
    LAST_MILE = "last_mile"


class RFQStatus(StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"
    FORCE_CLOSED = "force_closed"


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_.-]+(?: [A-Za-z0-9_.-]+)*$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.SUPPLIER

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return " ".join(str(value).split())


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    role: UserRole
    is_admin: bool = False


class BuyerProfile(BaseModel):
    id: int
    username: str
    email: EmailStr
    account_type: Literal["buyer"] = "buyer"
    created_at: datetime


class SupplierProfile(BaseModel):
    id: int
    username: str
    email: EmailStr
    account_type: Literal["supplier"] = "supplier"
    created_at: datetime
    transport_modes: list[TransportMode] = Field(default_factory=list)
    services: list[FreightService] = Field(default_factory=list)


class SupplierCapabilitiesUpdate(BaseModel):
    transport_modes: list[TransportMode] = Field(min_length=1, max_length=6)
    services: list[FreightService] = Field(default_factory=list, max_length=11)

    @field_validator("transport_modes", "services")
    @classmethod
    def categories_must_be_unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Category selections cannot contain duplicates")
        return value


class AdminUserSummary(UserPublic):
    created_at: datetime


class PaginatedUsers(BaseModel):
    items: list[AdminUserSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class Token(BaseModel):
    access_token: str
    token_type: str


class TriggerMode(StrEnum):
    BID_RECEIVED = "bid_received"
    RANK_CHANGE = "rank_change"
    L1_CHANGE = "l1_change"


class RFQCreate(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    remarks: str | None = Field(default=None, max_length=5000)
    origin: str = Field(min_length=2, max_length=160)
    destination: str = Field(min_length=2, max_length=160)
    transport_modes: list[TransportMode] = Field(min_length=1, max_length=6)
    services: list[FreightService] = Field(default_factory=list, max_length=11)
    bid_start_at: datetime
    initial_close_at: datetime
    forced_close_at: datetime
    pickup_service_date: date
    trigger_window_minutes: int = Field(gt=0, le=1440)
    extension_duration_minutes: int = Field(gt=0, le=1440)
    trigger_mode: TriggerMode

    @field_validator("origin", "destination")
    @classmethod
    def normalize_location(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Location must contain at least 2 characters")
        return value

    @field_validator("transport_modes", "services")
    @classmethod
    def categories_must_be_unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Category selections cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.bid_start_at.tzinfo is None or self.initial_close_at.tzinfo is None or self.forced_close_at.tzinfo is None:
            raise ValueError("auction timestamps must include a timezone")
        if self.bid_start_at >= self.initial_close_at:
            raise ValueError("bid_start_at must be before initial_close_at")
        if self.initial_close_at >= self.forced_close_at:
            raise ValueError("forced_close_at must be after initial_close_at")
        return self


class BidCreate(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=80)
    carrier_name: str = Field(min_length=2, max_length=160)
    freight_charges: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    origin_charges: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    destination_charges: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    transit_time_hours: int = Field(gt=0, le=10000)
    quote_valid_until: datetime

    @field_validator("quote_valid_until")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("quote_valid_until must include a timezone")
        return value


class BidResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    supplier_name: str
    carrier_name: str
    freight_charges: Decimal
    origin_charges: Decimal
    destination_charges: Decimal
    comparison_total: Decimal
    transit_time_hours: int
    quote_valid_until: datetime
    submitted_at: datetime
    accepted: bool
    rank: int | None = None


class ExtensionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    triggered_at: datetime
    previous_close_at: datetime
    new_close_at: datetime
    trigger_reason: str


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    message: str
    created_at: datetime


class RFQSummary(BaseModel):
    id: int
    reference_id: str
    name: str
    origin: str | None = None
    destination: str | None = None
    pickup_service_date: date
    transport_modes: list[TransportMode] = Field(default_factory=list)
    services: list[FreightService] = Field(default_factory=list)
    current_lowest_bid: Decimal | None
    bid_start_at: datetime
    current_close_at: datetime
    forced_close_at: datetime
    status: str
    trigger_mode: TriggerMode


class RFQDetail(RFQSummary):
    remarks: str | None = None
    initial_close_at: datetime
    trigger_window_minutes: int
    extension_duration_minutes: int
    bids: list[BidResponse]
    bid_total: int
    bid_page: int
    bid_page_size: int
    bid_has_more: bool
    extensions: list[ExtensionResponse]
    activities: list[ActivityResponse]


class AccountActivityItem(BaseModel):
    id: int
    action: str
    reference_id: str
    item_name: str
    status: str
    amount: Decimal | None = None
    occurred_at: datetime


class BuyerActivityItem(BaseModel):
    rfq_id: int
    auction_id: str
    auction_name: str
    status: str
    created_at: datetime


class SupplierActivityItem(BaseModel):
    bid_id: int
    rfq_id: int
    auction_id: str
    auction_name: str
    bid_status: str
    amount: Decimal
    submitted_at: datetime


class ActivityPage(BaseModel):
    items: list[AccountActivityItem | BuyerActivityItem | SupplierActivityItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class MetricPoint(BaseModel):
    label: str
    value: int


class AmountPoint(BaseModel):
    label: str
    count: int
    average_amount: Decimal | None = None


class AdminBuyerDetail(AdminUserSummary):
    role: Literal["buyer"] = "buyer"
    auctions_created: list[BuyerActivityItem]
    activity_total: int
    activity_page: int
    activity_page_size: int
    activity_has_more: bool


class AdminSupplierDetail(AdminUserSummary):
    role: Literal["supplier"] = "supplier"
    quotations_submitted: list[SupplierActivityItem]
    activity_total: int
    activity_page: int
    activity_page_size: int
    activity_has_more: bool


class PaginatedRFQs(BaseModel):
    items: list[RFQSummary]
    total: int
    page: int
    page_size: int
    has_more: bool


class BuyerAnalytics(BaseModel):
    rfq_total: int
    rfq_active: int
    rfq_closed: int
    quote_total: int
    average_quotes_per_rfq: Decimal
    status_breakdown: list[MetricPoint]
    activity_trend: list[MetricPoint]


class SupplierAnalytics(BaseModel):
    quote_total: int
    auctions_quoted: int
    leading_quotes: int
    average_quote: Decimal | None
    best_quote: Decimal | None
    activity_trend: list[AmountPoint]


class AdminAnalytics(BaseModel):
    user_total: int
    buyer_total: int
    supplier_total: int
    admin_total: int
    rfq_total: int
    rfq_active: int
    rfq_closed: int
    quote_total: int
    status_breakdown: list[MetricPoint]
    activity_trend: list[MetricPoint]
