from unittest.mock import MagicMock, patch

from installer.auth import generate_authelia_secrets, hash_authelia_password


def test_hash_authelia_password_parses_real_output_shape():

    # Real captured stdout from running this against a real, already-cached
    # image - no cold-cache pull noise.
    proc = MagicMock(
        returncode=0,
        stdout="Digest: $argon2id$v=19$m=65536,t=3,p=4$vI1aJgCiQEV5G+Gi7B3SIQ$gQC2ra+CruCi/BC/qO8PwMcmXH7p9D8AiR4q1kauetM\n"
    )

    with patch("installer.auth.subprocess.run", return_value=proc):

        result = hash_authelia_password("testpassword123")

    assert result == {
        "success": True,
        "error": None,
        "hash": "$argon2id$v=19$m=65536,t=3,p=4$vI1aJgCiQEV5G+Gi7B3SIQ$gQC2ra+CruCi/BC/qO8PwMcmXH7p9D8AiR4q1kauetM"
    }


def test_hash_authelia_password_skips_dockers_own_pull_digest_line():

    # Real captured stdout from a cold image cache - Docker's own pull
    # digest line also starts with "Digest: ", confirmed by actually
    # running this against an uncached image.
    proc = MagicMock(
        returncode=0,
        stdout=(
            "Unable to find image 'authelia/authelia:latest' locally\n"
            "latest: Pulling from authelia/authelia\n"
            "Digest: sha256:1b363e9279e742397966333f364e0876ae02bf5c876de73e83af6d48c57ff51b\n"
            "Status: Downloaded newer image for authelia/authelia:latest\n"
            "Digest: $argon2id$v=19$m=65536,t=3,p=4$TLCfiWWEDGH4go0pBWto+g$Ik+8rK4fVaES7hcRhJZtFjoWfbFwBSoPTe6xoCDw18w\n"
        )
    )

    with patch("installer.auth.subprocess.run", return_value=proc):

        result = hash_authelia_password("testpassword123")

    assert result["success"] is True
    assert result["hash"] == "$argon2id$v=19$m=65536,t=3,p=4$TLCfiWWEDGH4go0pBWto+g$Ik+8rK4fVaES7hcRhJZtFjoWfbFwBSoPTe6xoCDw18w"


def test_hash_authelia_password_nonzero_exit_reports_clean_error():

    proc = MagicMock(returncode=1, stdout="")

    with patch("installer.auth.subprocess.run", return_value=proc):

        result = hash_authelia_password("testpassword123")

    assert result == {
        "success": False,
        "error": "Failed to hash password via authelia's own CLI.",
        "hash": None
    }


def test_hash_authelia_password_missing_digest_line_reports_clean_error():

    proc = MagicMock(returncode=0, stdout="something unexpected\n")

    with patch("installer.auth.subprocess.run", return_value=proc):

        result = hash_authelia_password("testpassword123")

    assert result == {
        "success": False,
        "error": "Could not find a password hash in authelia's output.",
        "hash": None
    }


def test_generate_authelia_secrets_writes_three_files(tmp_path):

    secrets_dir = tmp_path / "secrets"
    generate_authelia_secrets(secrets_dir)

    jwt = (secrets_dir / "JWT_SECRET").read_text()
    session = (secrets_dir / "SESSION_SECRET").read_text()
    storage = (secrets_dir / "STORAGE_ENCRYPTION_KEY").read_text()

    assert len(jwt) == 64
    assert len(session) == 64
    assert len(storage) == 64
    assert len({jwt, session, storage}) == 3


def test_generate_authelia_secrets_never_overwrites_existing_files(tmp_path):

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    (secrets_dir / "JWT_SECRET").write_text("existing-real-secret")

    generate_authelia_secrets(secrets_dir)

    assert (secrets_dir / "JWT_SECRET").read_text() == "existing-real-secret"
    assert (secrets_dir / "SESSION_SECRET").exists()
    assert (secrets_dir / "STORAGE_ENCRYPTION_KEY").exists()
