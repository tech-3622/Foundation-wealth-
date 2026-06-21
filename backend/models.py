from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, JSON, ForeignKey, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
import enum

from backend.database import Base


class UserRole(str, enum.Enum):
    USER = "user"
    ADMIN = "admin"


class KYCStatus(str, enum.Enum):
    NONE = "none"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class TradeSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class TradeType(str, enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TradeStatus(str, enum.Enum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class AlgoStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    ARCHIVED = "archived"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    country = Column(String, nullable=True)
    ssn = Column(String, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default=UserRole.USER.value)
    verified = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    verification_code = Column(String, nullable=True)
    verification_code_expires = Column(DateTime, nullable=True)
    kyc_status = Column(String, default=KYCStatus.NONE.value)
    kyc_document = Column(String, nullable=True)
    date_of_birth = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    occupation = Column(String, nullable=True)
    id_type = Column(String, nullable=True)
    id_front_path = Column(String, nullable=True)
    id_back_path = Column(String, nullable=True)
    kyc_submitted_at = Column(DateTime, nullable=True)
    kyc_reviewed_at = Column(DateTime, nullable=True)
    kyc_rejection_reason = Column(Text, nullable=True)
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String, nullable=True)
    profile_photo_path = Column(String, nullable=True)
    notification_prefs = Column(Text, default="{}")
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    app_passwords = relationship("AppPassword", back_populates="user", cascade="all, delete-orphan")
    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    algorithms = relationship("Algorithm", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    watchlists = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    withdrawals = relationship("Withdrawal", foreign_keys="Withdrawal.user_id", back_populates="user", cascade="all, delete-orphan")


class AppPassword(Base):
    __tablename__ = "app_passwords"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    last_used = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="app_passwords")


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String, nullable=False)
    quantity = Column(Float, default=0.0)
    avg_price = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="portfolios")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    type = Column(String, nullable=False)
    quantity = Column(Float, nullable=False)
    price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    filled_price = Column(Float, nullable=True)
    filled_quantity = Column(Float, default=0.0)
    status = Column(String, default=TradeStatus.PENDING.value)
    total = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="trades")


class Algorithm(Base):
    __tablename__ = "algorithms"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String, default="python")
    code = Column(Text, nullable=False)
    status = Column(String, default=AlgoStatus.DRAFT.value)
    config = Column(JSON, default=dict)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="algorithms")
    backtests = relationship("Backtest", back_populates="algorithm", cascade="all, delete-orphan")


class Backtest(Base):
    __tablename__ = "backtests"

    id = Column(Integer, primary_key=True, index=True)
    algo_id = Column(Integer, ForeignKey("algorithms.id"), nullable=False)
    symbol = Column(String, nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    initial_capital = Column(Float, default=10000.0)
    result = Column(JSON, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    algorithm = relationship("Algorithm", back_populates="backtests")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="notifications")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, default="Default")
    symbols = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="watchlists")


class Deposit(Base):
    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=False)  # "crypto" or "gift_card"
    method_details = Column(JSON, default=dict)  # crypto: {currency, tx_hash} | gift_card: {card_type, code}
    status = Column(String, default="pending")  # pending, approved, rejected
    direct_deposit = Column(Boolean, default=False)
    receipt_path = Column(String, nullable=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id])
    admin = relationship("User", foreign_keys=[admin_id])


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)  # BTC, SOL, USDT, ETH
    wallet_address = Column(String, nullable=False)
    network = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected
    receipt_path = Column(String, nullable=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    admin_note = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = Column(DateTime, nullable=True)

    user = relationship("User", foreign_keys=[user_id], back_populates="withdrawals")
    admin = relationship("User", foreign_keys=[admin_id])


class BonusCode(Base):
    __tablename__ = "bonus_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, unique=True, index=True, nullable=False)
    amount_usd = Column(Float, nullable=False, default=15.0)
    currency = Column(String, default="SOL")
    max_claims = Column(Integer, default=1)
    claim_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)

    creator = relationship("User", foreign_keys=[created_by])


class BonusClaim(Base):
    __tablename__ = "bonus_claims"

    id = Column(Integer, primary_key=True, index=True)
    bonus_code_id = Column(Integer, ForeignKey("bonus_codes.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount_credited = Column(Float, nullable=False)
    currency = Column(String, default="SOL")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    bonus_code = relationship("BonusCode")
    user = relationship("User", foreign_keys=[user_id])


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
