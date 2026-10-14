from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reorder_threshold: Mapped[float] = mapped_column(Float, default=0.0)
    bom_items: Mapped[list["BOMItem"]] = relationship(back_populates="product")
    order_history: Mapped[list["OrderHistory"]] = relationship(back_populates="product")


class OrderHistory(Base):
    __tablename__ = "order_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[float] = mapped_column(Float)

    product: Mapped[Product] = relationship(back_populates="order_history")


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bom_items: Mapped[list["BOMItem"]] = relationship(back_populates="material")
    inventory_rows: Mapped[list["Inventory"]] = relationship(back_populates="material")


class BOMItem(Base):
    __tablename__ = "bom_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[float] = mapped_column(Float, default=1.0)

    product: Mapped[Product] = relationship(back_populates="bom_items")
    material: Mapped[Material] = relationship(back_populates="bom_items")

    __table_args__ = (UniqueConstraint("product_id", "material_id"),)


class Inventory(Base):
    __tablename__ = "inventory"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), unique=True)
    available_qty: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)

    material: Mapped[Material] = relationship(back_populates="inventory_rows")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    is_cold_start: Mapped[bool] = mapped_column(Boolean, default=False)
    supplier_materials: Mapped[list["SupplierMaterial"]] = relationship(back_populates="supplier")
    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")


class SupplierMaterial(Base):
    __tablename__ = "supplier_materials"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    unit_price: Mapped[float] = mapped_column(Float)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    minimum_order_qty: Mapped[int] = mapped_column(Integer, default=0)
    on_time_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    defect_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    past_orders: Mapped[int] = mapped_column(Integer, default=0)

    supplier: Mapped[Supplier] = relationship(back_populates="supplier_materials")
    material: Mapped[Material] = relationship()

    __table_args__ = (UniqueConstraint("supplier_id", "material_id"),)


class ProductionRun(Base):
    __tablename__ = "production_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True)
    product_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[float] = mapped_column(Float)
    due_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    urgency: Mapped[str] = mapped_column(String(32), default="normal")
    status: Mapped[str] = mapped_column(String(64), default="pending")
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    eta_minutes: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivery_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="run")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="run")
    events: Mapped[list["EventLog"]] = relationship(back_populates="run")


class SupplierHistory(Base):
    __tablename__ = "supplier_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), default="received")
    status: Mapped[str] = mapped_column(String(64), default="ok")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("production_runs.run_id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"))
    quantity: Mapped[float] = mapped_column(Float)
    unit_price: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(64), default="created")

    run: Mapped[ProductionRun] = relationship(back_populates="purchase_orders")
    supplier: Mapped[Supplier] = relationship(back_populates="purchase_orders")


class EventLog(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("production_runs.id"), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    sender: Mapped[str] = mapped_column(String(128))
    receiver: Mapped[str] = mapped_column(String(128), default="system")
    type: Mapped[str] = mapped_column(String(32), default="info")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(32), default="info")

    run: Mapped[ProductionRun | None] = relationship(back_populates="events")


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("production_runs.id"))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    run: Mapped[ProductionRun] = relationship(back_populates="approvals")


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)


from .config import DATABASE_URL


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DATABASE_URL = normalize_database_url(DATABASE_URL)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_db_and_tables() -> None:
    Base.metadata.create_all(engine)
