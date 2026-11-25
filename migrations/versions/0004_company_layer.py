"""company layer: alert subscriptions, alternate-source reviews, data verifications, benchmark submissions

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alert_subscription',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('channel', sa.String(length=8), nullable=False),
    sa.Column('target', sa.String(length=600), nullable=False),
    sa.Column('target_hash', sa.String(length=64), nullable=False),
    sa.Column('material_ids', sa.JSON(), nullable=False),
    sa.Column('confirmed', sa.Boolean(), nullable=False),
    sa.Column('confirm_token_hash', sa.String(length=64), nullable=True),
    sa.Column('manage_token_hash', sa.String(length=64), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_sent_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('channel', 'target_hash', name='uq_alert_target')
    )
    op.create_index(op.f('ix_alert_subscription_target_hash'), 'alert_subscription', ['target_hash'], unique=False)
    op.create_index(op.f('ix_alert_subscription_confirm_token_hash'), 'alert_subscription', ['confirm_token_hash'], unique=False)
    op.create_index(op.f('ix_alert_subscription_manage_token_hash'), 'alert_subscription', ['manage_token_hash'], unique=False)
    op.create_table('alternate_source_review',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('material_id', sa.String(length=64), nullable=False),
    sa.Column('country', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('evidence_url', sa.String(length=512), nullable=False),
    sa.Column('evidence_note', sa.String(length=1000), nullable=False),
    sa.Column('reviewer', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['material_id'], ['material.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alternate_source_review_material_id'), 'alternate_source_review', ['material_id'], unique=False)
    op.create_table('data_verification',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('material_id', sa.String(length=64), nullable=False),
    sa.Column('data_group', sa.String(length=16), nullable=False),
    sa.Column('source_doc', sa.String(length=300), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('note', sa.String(length=1000), nullable=False),
    sa.Column('reviewer', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['material_id'], ['material.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_data_verification_material_id'), 'data_verification', ['material_id'], unique=False)
    op.create_table('benchmark_submission',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sector', sa.String(length=32), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_benchmark_submission_sector'), 'benchmark_submission', ['sector'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_benchmark_submission_sector'), table_name='benchmark_submission')
    op.drop_table('benchmark_submission')
    op.drop_index(op.f('ix_data_verification_material_id'), table_name='data_verification')
    op.drop_table('data_verification')
    op.drop_index(op.f('ix_alternate_source_review_material_id'), table_name='alternate_source_review')
    op.drop_table('alternate_source_review')
    op.drop_index(op.f('ix_alert_subscription_manage_token_hash'), table_name='alert_subscription')
    op.drop_index(op.f('ix_alert_subscription_confirm_token_hash'), table_name='alert_subscription')
    op.drop_index(op.f('ix_alert_subscription_target_hash'), table_name='alert_subscription')
    op.drop_table('alert_subscription')
