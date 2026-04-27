"""Coverage gap filler for turing/self_nodes.py remaining uncovered lines.

Spec: note_hobby with sqlite IntegrityError, note_interest with sqlite
IntegrityError, practice_skill raising stored_level (line 181).

Acceptance criteria:
- note_hobby IntegrityError is caught and re-raised as ValueError
- note_interest IntegrityError is caught and re-raised as ValueError
- practice_skill with valid new_level sets stored_level correctly
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_model import Hobby, Interest, SkillKind
from turing.self_nodes import note_hobby, note_interest, note_skill, practice_skill


class TestHobbyIntegrityError:
    def test_duplicate_hobby_name_raises_value_error(self, srepo, bootstrapped_id, new_id) -> None:
        srepo.insert_hobby(
            Hobby(
                node_id="hobby:manual",
                self_id=bootstrapped_id,
                name="Reading",
                description="books",
            )
        )
        with pytest.raises(ValueError, match="duplicate hobby"):
            note_hobby(srepo, bootstrapped_id, "Reading", "books again", new_id)


class TestInterestIntegrityError:
    def test_duplicate_interest_topic_raises_value_error(
        self, srepo, bootstrapped_id, new_id
    ) -> None:
        srepo.insert_interest(
            Interest(
                node_id="interest:manual",
                self_id=bootstrapped_id,
                topic="Physics",
                description="quantum",
            )
        )
        with pytest.raises(ValueError, match="duplicate interest"):
            note_interest(srepo, bootstrapped_id, "Physics", "classical", new_id)


class TestPracticeSkillRaiseLevel:
    def test_practice_raises_stored_level(self, srepo, bootstrapped_id, new_id) -> None:
        s = note_skill(srepo, bootstrapped_id, "python", 0.5, SkillKind.INTELLECTUAL, new_id)
        updated = practice_skill(srepo, bootstrapped_id, s.node_id, new_level=0.8)
        assert updated.stored_level == 0.8
