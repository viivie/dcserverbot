"""Optional Google Drive backup for the SQLite database."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from config import Config


LOGGER = logging.getLogger("fumao-worship-bot.google-drive")
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _is_storage_quota_error(error: Exception) -> bool:
    response = getattr(error, "resp", None)
    return getattr(response, "status", None) == 403 and "storageQuotaExceeded" in str(error)


class GoogleDriveBackup:
    def __init__(self, config: Config):
        self.key_file = Path(config.google_drive_key_file)
        self.folder_id = config.google_drive_folder_id
        self.filename = config.google_drive_filename
        self.interval = config.google_drive_backup_interval

    @property
    def enabled(self) -> bool:
        return self.key_file.is_file() and bool(self.folder_id)

    async def run_periodically(self, database_path: Path) -> None:
        if not self.enabled:
            return

        while True:
            try:
                await asyncio.to_thread(self.backup_now, database_path)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if _is_storage_quota_error(error):
                    LOGGER.error(
                        "Google Drive backup needs a Shared Drive: service accounts "
                        "cannot upload to My Drive because they have no storage quota"
                    )
                else:
                    LOGGER.exception("Google Drive database backup failed")
            await asyncio.sleep(self.interval)

    def backup_now(self, database_path: Path) -> None:
        snapshot_path: Path | None = None
        try:
            snapshot_path = self._create_snapshot(database_path)
            service = self._build_service()
            query = (
                f"name = '{_escape_drive_query(self.filename)}' "
                f"and '{_escape_drive_query(self.folder_id)}' in parents "
                "and trashed = false"
            )
            files = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    pageSize=1,
                    fields="files(id,name)",
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                )
                .execute()
                .get("files", [])
            )

            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(
                str(snapshot_path),
                mimetype="application/x-sqlite3",
                resumable=False,
            )
            if files:
                service.files().update(
                    fileId=files[0]["id"],
                    media_body=media,
                    supportsAllDrives=True,
                ).execute()
                LOGGER.info("backed up %s to Google Drive", database_path.name)
            else:
                service.files().create(
                    body={"name": self.filename, "parents": [self.folder_id]},
                    media_body=media,
                    fields="id",
                    supportsAllDrives=True,
                ).execute()
                LOGGER.info("created Google Drive backup %s", self.filename)
        finally:
            if snapshot_path is not None:
                snapshot_path.unlink(missing_ok=True)

    @staticmethod
    def _create_snapshot(database_path: Path) -> Path:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix="fumao-database-",
            suffix=".db",
        )
        os.close(file_descriptor)
        snapshot_path = Path(temporary_name)
        try:
            with sqlite3.connect(database_path) as source, sqlite3.connect(snapshot_path) as target:
                source.backup(target)
        except Exception:
            snapshot_path.unlink(missing_ok=True)
            raise
        return snapshot_path

    def _build_service(self):
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        try:
            credentials_info = json.loads(self.key_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"無法讀取 Google Drive 金鑰檔：{self.key_file}") from exc
        if not isinstance(credentials_info, dict):
            raise ValueError(f"Google Drive 金鑰檔必須是 JSON 物件：{self.key_file}")
        credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=[DRIVE_SCOPE],
        )
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
