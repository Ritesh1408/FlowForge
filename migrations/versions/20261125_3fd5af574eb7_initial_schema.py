"""initial schema

Revision ID: 3fd5af574eb7
Revises: 
Create Date: 2026-11-25 10:37:48.668340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3fd5af574eb7'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('workflows',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('definition', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflows')),
    sa.UniqueConstraint('name', name=op.f('uq_workflows_name'))
    )
    op.create_table('executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workflow_id', sa.Uuid(), nullable=False),
    sa.Column('definition_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.Text(), server_default='QUEUED', nullable=False),
    sa.Column('input', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('QUEUED', 'RUNNING', 'RETRYING', 'COMPLETED', 'FAILED', 'CANCELLED')", name=op.f('ck_executions_status')),
    sa.ForeignKeyConstraint(['workflow_id'], ['workflows.id'], name=op.f('fk_executions_workflow_id_workflows'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_executions'))
    )
    op.create_table('execution_steps',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('status', sa.Text(), server_default='PENDING', nullable=False),
    sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'RETRYING', 'COMPLETED', 'FAILED', 'SKIPPED', 'CANCELLED')", name=op.f('ck_execution_steps_status')),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_execution_steps_execution_id_executions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_steps')),
    sa.UniqueConstraint('execution_id', 'position', name=op.f('uq_execution_steps_execution_id_position'))
    )
    op.create_table('execution_logs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=False),
    sa.Column('step_id', sa.Uuid(), nullable=True),
    sa.Column('level', sa.String(length=20), nullable=False),
    sa.Column('event', sa.String(length=100), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_execution_logs_execution_id_executions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['step_id'], ['execution_steps.id'], name=op.f('fk_execution_logs_step_id_execution_steps'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_logs'))
    )
    op.create_index(op.f('ix_execution_logs_execution_id_created_at'), 'execution_logs', ['execution_id', 'created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_execution_logs_execution_id_created_at'), table_name='execution_logs')
    op.drop_table('execution_logs')
    op.drop_table('execution_steps')
    op.drop_table('executions')
    op.drop_table('workflows')
