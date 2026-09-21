from pgproof.adapters.sql.fingerprint import fingerprint_query


def test_fingerprint_has_the_sha256_shape() -> None:
    value = fingerprint_query("SELECT 1", (), ())
    assert value.startswith("sha256:")
    assert len(value) == len("sha256:") + 64
    int(value.removeprefix("sha256:"), 16)  # every character is hex


def test_fingerprint_is_deterministic() -> None:
    a = fingerprint_query("SELECT id FROM orders", ("public.orders",), ("integer",))
    b = fingerprint_query("SELECT id FROM orders", ("public.orders",), ("integer",))
    assert a == b


def test_fingerprint_is_sensitive_to_normalized_sql() -> None:
    a = fingerprint_query("SELECT id FROM orders", (), ())
    b = fingerprint_query("SELECT name FROM orders", (), ())
    assert a != b


def test_fingerprint_is_sensitive_to_relations() -> None:
    a = fingerprint_query("SELECT 1", ("public.orders",), ())
    b = fingerprint_query("SELECT 1", ("public.tenants",), ())
    assert a != b


def test_fingerprint_relations_are_order_independent() -> None:
    a = fingerprint_query("SELECT 1", ("public.orders", "public.tenants"), ())
    b = fingerprint_query("SELECT 1", ("public.tenants", "public.orders"), ())
    assert a == b


def test_fingerprint_is_sensitive_to_parameter_types() -> None:
    a = fingerprint_query("SELECT 1", (), ("integer",))
    b = fingerprint_query("SELECT 1", (), ("text",))
    assert a != b


def test_fingerprint_parameter_type_order_matters() -> None:
    a = fingerprint_query("SELECT 1", (), ("integer", "text"))
    b = fingerprint_query("SELECT 1", (), ("text", "integer"))
    assert a != b
