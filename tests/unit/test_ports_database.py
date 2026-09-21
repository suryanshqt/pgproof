from pgproof.ports.database import GeneratedCredentials


def test_dsn_embeds_every_field() -> None:
    credentials = GeneratedCredentials(
        host="127.0.0.1", port=54321, user="pgproof", password="s3cr3t", database="pgproof"
    )
    assert credentials.dsn == "postgresql://pgproof:s3cr3t@127.0.0.1:54321/pgproof"
