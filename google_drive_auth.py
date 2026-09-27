"""Create the Google Drive OAuth token used by the bot's backup task."""

from __future__ import annotations

import os
from pathlib import Path

from config import BOT_DIR


SCOPES = ["https://www.googleapis.com/auth/drive"]


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_file = Path(
        os.getenv(
            "GOOGLE_DRIVE_OAUTH_CLIENT_FILE",
            str(BOT_DIR / "credentials" / "google_drives.json"),
        )
    )
    token_file = Path(
        os.getenv(
            "GOOGLE_DRIVE_OAUTH_TOKEN_FILE",
            str(client_file.with_name("google_drive_token.json")),
        )
    )
    if not client_file.is_file():
        raise SystemExit(f"找不到 Google OAuth Client JSON：{client_file}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    credentials = flow.run_local_server(port=0)
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"Google Drive OAuth token 已儲存至：{token_file}")


if __name__ == "__main__":
    main()
