from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Integer, String, Table, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


album_images = Table(
    "album_images",
    Base.metadata,
    Column("album_id", String(36), ForeignKey("albums.id", ondelete="CASCADE"), primary_key=True),
    Column("image_id", String(36), ForeignKey("generated_images.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    firebase_uid: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    generations: Mapped[list["Generation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    images: Mapped[list["GeneratedImage"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    albums: Mapped[list["Album"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["CreditTransaction"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Generation(Base):
    __tablename__ = "generations"
    __table_args__ = (UniqueConstraint("guest_session_id", name="uq_generation_guest_session"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    guest_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    gender: Mapped[str] = mapped_column(String(40))
    age_range: Mapped[str] = mapped_column(String(40))
    ethnicity: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    image_count: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    user: Mapped[User | None] = relationship(back_populates="generations")
    images: Mapped[list["GeneratedImage"]] = relationship(back_populates="generation", cascade="all, delete-orphan")


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    generation_id: Mapped[str] = mapped_column(ForeignKey("generations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    generation: Mapped[Generation] = relationship(back_populates="images")
    user: Mapped[User | None] = relationship(back_populates="images")
    albums: Mapped[list["Album"]] = relationship(secondary=album_images, back_populates="images")


class Album(Base):
    __tablename__ = "albums"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    user: Mapped[User] = relationship(back_populates="albums")
    images: Mapped[list[GeneratedImage]] = relationship(secondary=album_images, back_populates="albums")


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    credits: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    reference_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    user: Mapped[User] = relationship(back_populates="transactions")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pack_code: Mapped[str] = mapped_column(String(40))
    credits: Mapped[int] = mapped_column(Integer)
    amount_kes: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    provider_reference: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    checkout_request_id: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)
