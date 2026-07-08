"""add person profile fields — socials, nationalities, residence (issue #49)

Extends the per-project people directory (issue #40) with three optional profile
fields for the add/edit person modal:
  * socials_json      — JSON list of {"network": str, "handle": str} so a person
                        can carry several social links (Instagram, Facebook,
                        Polarsteps, Strava, …). The dedicated `polarsteps` column
                        is kept and mirrored from the Polarsteps entry so the
                        "view a person's shared trip" feature is unaffected.
  * nationalities_json — JSON list of ISO 3166-1 alpha-2 country codes.
  * residence         — free-text "city, country" where the person lives, filled
                        via city autocomplete (stored as the display string).

All nullable, so existing rows are unaffected.

Revision ID: f7e8d9c0b1a2
Revises: d5b1c0a2e3f4
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7e8d9c0b1a2'
down_revision: Union[str, Sequence[str], None] = 'd5b1c0a2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('person', sa.Column('socials_json', sa.String(), nullable=True))
    op.add_column('person', sa.Column('nationalities_json', sa.String(), nullable=True))
    op.add_column('person', sa.Column('residence', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('person', 'residence')
    op.drop_column('person', 'nationalities_json')
    op.drop_column('person', 'socials_json')
