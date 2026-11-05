"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "instruments",
        sa.Column("ticker", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False, server_default=""),
        sa.Column("asset_class", sa.String(16), nullable=False, server_default="equity"),
        sa.Column("exchange", sa.String(16), nullable=False, server_default="US"),
        sa.Column("country", sa.String(8), nullable=False, server_default="US"),
        sa.Column("sector", sa.String(64), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(32), sa.ForeignKey("instruments.ticker"), index=True),
        sa.Column("quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("avg_cost", sa.Float, nullable=False, server_default="0"),
        sa.Column("opened_at", sa.Date, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_table(
        "transactions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(32), sa.ForeignKey("instruments.ticker"), index=True),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("quantity", sa.Float, nullable=False),
        sa.Column("price", sa.Float, nullable=False),
        sa.Column("fees", sa.Float, nullable=False, server_default="0"),
        sa.Column("executed_at", sa.Date, nullable=False),
    )
    op.create_table(
        "dividends",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(32), sa.ForeignKey("instruments.ticker"), index=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("paid_at", sa.Date, nullable=False),
    )
    op.create_table(
        "portfolio_settings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("base_currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("capital_available", sa.Float, nullable=False, server_default="0"),
        sa.Column("monthly_contribution", sa.Float, nullable=False, server_default="0"),
        sa.Column("risk_tolerance", sa.String(16), nullable=False, server_default="moderate"),
        sa.Column("horizon_years", sa.Float, nullable=False, server_default="15"),
        sa.Column("max_weight_per_asset", sa.Float, nullable=False, server_default="0.25"),
        sa.Column("max_weight_per_sector", sa.Float, nullable=False, server_default="0.40"),
        sa.Column("min_cash", sa.Float, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    for t in ("portfolio_settings", "dividends", "transactions", "positions", "instruments"):
        op.drop_table(t)
