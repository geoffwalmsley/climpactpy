"""Checks on the hosting files in deploy/ (#123)."""

from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[3] / "deploy"


def test_cloud_init_is_plain_ascii():
    """deploy/cloud-init.yaml is pasted into DigitalOcean's user-data box, and a paste that
    mangles one non-ASCII character (a clipboard without a UTF-8 locale turns "›" into
    "âº", with a C1 control byte) makes cloud-init reject the whole file and set up
    nothing. So the file holds printable ASCII, tabs and newlines only."""
    text = (DEPLOY / "cloud-init.yaml").read_bytes()
    bad = sorted(
        {
            (n, line.decode("utf-8", "replace").strip())
            for n, line in enumerate(text.splitlines(), 1)
            if any(b > 0x7E or (b < 0x20 and b != 0x09) for b in line)
        }
    )
    assert not bad, f"non-ASCII or control characters in cloud-init.yaml: {bad}"
    assert text.startswith(b"#cloud-config\n")
