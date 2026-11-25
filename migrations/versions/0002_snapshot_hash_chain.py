"""snapshot hash chain

Adds the previous-entry digest and the entry digest to score_snapshot (patent claim 5). Existing rows keep NULL
digests and are reported as unchained legacy entries by the log verifier.

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("score_snapshot") as b:
        b.add_column(sa.Column("prev_digest", sa.String(length=64), nullable=True))
        b.add_column(sa.Column("digest", sa.String(length=64), nullable=True))
        b.create_index("ix_score_snapshot_digest", ["digest"], unique=False)
        b.create_unique_constraint("uq_score_snapshot_prev_digest", ["prev_digest"])


def downgrade():
    with op.batch_alter_table("score_snapshot") as b:
        b.drop_constraint("uq_score_snapshot_prev_digest", type_="unique")
        b.drop_index("ix_score_snapshot_digest")
        b.drop_column("digest")
        b.drop_column("prev_digest")
