from __future__ import annotations

import base64
import hashlib

from app.werewolf.system_player_avatar_data import SYSTEM_AVATAR_DATA_BASE64


EXPECTED_SYSTEM_AVATARS = {
    "system-gothic-female-1": (
        2_667_466,
        "8d6be6f675574981ab96d5989fb2fecb0a3650d72f24502c87e6ef7b7fc9b822",
    ),
    "system-gothic-female-2": (
        2_373_306,
        "21b5cffac019bf67119e2bfc3748b091eb925a8c38970d09a06b2312df8f6acc",
    ),
    "system-gothic-male-1": (
        2_547_605,
        "82850b367b334a5d992a1f1fe732eb5b5c62f9254e904ecf3a3847bcb14f06ae",
    ),
    "system-gothic-male-2": (
        1_935_942,
        "1ca2e7d668ddc064771f22ee3bd9f29c9a385563695420f42b76d5767dc1d5a3",
    ),
}


def test_embedded_system_avatar_base64_matches_original_assets() -> None:
    assert set(SYSTEM_AVATAR_DATA_BASE64) == set(EXPECTED_SYSTEM_AVATARS)

    for asset_id, (expected_size, expected_sha256) in EXPECTED_SYSTEM_AVATARS.items():
        data = base64.b64decode(SYSTEM_AVATAR_DATA_BASE64[asset_id], validate=True)
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) == expected_size
        assert hashlib.sha256(data).hexdigest() == expected_sha256
