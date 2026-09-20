"""The rule registry: every rule id is unique and matches its module's `RULE_ID`."""

from pgproof.rules import RULES
from pgproof.rules import schema as schema_rule
from pgproof.rules import tenancy as tenancy_rule
from pgproof.rules import workload as workload_rule


def test_rule_ids_are_unique() -> None:
    ids = [rule.id for rule in RULES]
    assert len(ids) == len(set(ids))


def test_the_registry_carries_exactly_the_three_ring_a_rules() -> None:
    ids = {rule.id for rule in RULES}
    assert ids == {schema_rule.RULE_ID, workload_rule.RULE_ID, tenancy_rule.RULE_ID}


def test_every_rule_starts_at_version_one() -> None:
    assert all(rule.version == 1 for rule in RULES)
