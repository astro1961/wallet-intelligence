"""Bulk wallet import parsing, validation, deduplication, preview, and application."""
from __future__ import annotations

import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.wallet_manager import WalletManager
from app.database.models import Network, Wallet, WalletGroup, WalletNetwork
from app.utils.validators import (
    is_valid_evm_address,
    is_valid_solana_address,
    normalize_evm_address,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass
class ImportRow:
    """A single parsed row from an import payload."""

    address: str
    name: str | None = None
    group: str | None = None
    network: str | None = None
    tags: list[str] = field(default_factory=list)
    status: str = "pending"  # "new" | "duplicate" | "error" | "skipped" | "added" | "updated"
    error: str | None = None


@dataclass
class ImportPreview:
    """Preview of parsed rows, validation state, and projected counts."""

    format: str
    rows: list[ImportRow]
    new_count: int
    duplicate_count: int
    error_count: int
    default_group_id: int | None = None


@dataclass
class ImportReport:
    """Execution summary report of an applied import batch."""

    added: int
    updated: int
    skipped: int
    errors: list[ImportRow]
    rows: list[ImportRow]


class ImportManager:
    """Handles bulk wallet imports from CSV, TXT, and JSON sources."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def detect_format(self, text: str) -> str:
        """Detect whether input is 'csv', 'txt', or 'json'."""
        cleaned = text.strip()
        if cleaned.startswith(("{", "[")):
            try:
                parsed = json.loads(cleaned)
                if isinstance(parsed, (list, dict)):
                    return "json"
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("Format detection: input is not valid JSON (%s)", exc)

        lines = [
            line.strip()
            for line in cleaned.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if lines:
            header = lines[0].lower()
            if "address" in header and any(k in header for k in ("name", "group", "network", "tags")):
                return "csv"

        return "txt"

    def _parse_tags(self, raw_tags: Any) -> list[str]:
        """Parse tags from string or list into a list of clean tag names."""
        if not raw_tags:
            return []
        if isinstance(raw_tags, (list, tuple, set)):
            return [str(t).strip() for t in raw_tags if str(t).strip()]
        if isinstance(raw_tags, str):
            return [t.strip() for t in re.split(r"[,;]", raw_tags) if t.strip()]
        return [str(raw_tags).strip()]

    def _parse_csv(self, text: str) -> list[ImportRow]:
        """Parse CSV text with header into ImportRow objects."""
        reader = csv.reader(io.StringIO(text.strip()))
        rows: list[ImportRow] = []

        header: list[str] | None = None
        for raw_line in reader:
            if not raw_line or all(not str(c).strip() for c in raw_line):
                continue
            if header is None:
                header = [c.strip().lower() for c in raw_line]
                continue

            row_dict = {
                header[i]: raw_line[i].strip()
                for i in range(min(len(header), len(raw_line)))
            }
            address = row_dict.get("address", "")
            name = row_dict.get("name") or None
            group = row_dict.get("group") or None
            network = row_dict.get("network") or None
            tags = self._parse_tags(row_dict.get("tags"))

            rows.append(
                ImportRow(
                    address=address,
                    name=name,
                    group=group,
                    network=network,
                    tags=tags,
                )
            )
        return rows

    def _parse_txt(self, text: str) -> list[ImportRow]:
        """Parse TXT lines into ImportRow objects."""
        rows: list[ImportRow] = []
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned or cleaned.startswith("#"):
                continue

            if "," in cleaned:
                parts = [p.strip() for p in cleaned.split(",", 1)]
                address = parts[0]
                name = parts[1] if len(parts) > 1 and parts[1] else None
            else:
                address = cleaned
                name = None

            rows.append(ImportRow(address=address, name=name))
        return rows

    def _parse_json(self, text: str) -> list[ImportRow]:
        """Parse JSON array of objects into ImportRow objects."""
        data = json.loads(text.strip())
        if isinstance(data, dict):
            data = [data]

        rows: list[ImportRow] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            address = str(item.get("address", "")).strip()
            name = str(item["name"]).strip() if item.get("name") else None
            group = str(item["group"]).strip() if item.get("group") else None
            network = str(item["network"]).strip() if item.get("network") else None
            tags = self._parse_tags(item.get("tags"))

            rows.append(
                ImportRow(
                    address=address,
                    name=name,
                    group=group,
                    network=network,
                    tags=tags,
                )
            )
        return rows

    def preview(
        self,
        text: str,
        fmt: str | None = None,
        default_group_id: int | None = None,
    ) -> ImportPreview:
        """Parse and validate import data without writing to the database."""
        chosen_format = (fmt or self.detect_format(text)).lower()

        if chosen_format == "csv":
            rows = self._parse_csv(text)
        elif chosen_format == "json":
            rows = self._parse_json(text)
        else:
            chosen_format = "txt"
            rows = self._parse_txt(text)

        # Pre-fetch known networks (case-insensitive name lookup from DB and config)
        existing_networks = list(self.session.execute(select(Network)).scalars().all())
        known_networks = {n.name.lower() for n in existing_networks}
        try:
            from app.config import load_config

            cfg = load_config()
            for net_cfg in cfg.networks:
                known_networks.add(net_cfg.name.strip().lower())
        except (AttributeError, ValueError, KeyError) as exc:
            logger.warning("Could not pre-fetch networks from config: %s", exc)

        seen_in_batch: set[tuple[str, str]] = set()

        new_count = 0
        duplicate_count = 0
        error_count = 0

        for idx, row in enumerate(rows, start=1):
            addr_str = row.address.strip()
            if not addr_str:
                row.status = "error"
                row.error = "Address is empty"
                logger.warning("Row %d skipped: %s", idx, row.error)
                error_count += 1
                continue

            # Validate network if specified
            if row.network:
                net_key = row.network.strip().lower()
                if net_key not in known_networks:
                    row.status = "error"
                    row.error = f"Unknown network: '{row.network}'"
                    logger.warning("Row %d skipped: %s", idx, row.error)
                    error_count += 1
                    continue

            # Validate address format and determine chain type
            if is_valid_evm_address(addr_str):
                chain_type = "evm"
                norm_key = normalize_evm_address(addr_str).lower()
            elif is_valid_solana_address(addr_str):
                chain_type = "solana"
                norm_key = addr_str
            else:
                row.status = "error"
                row.error = f"Invalid EVM or Solana address: '{row.address}'"
                logger.warning("Row %d skipped: %s", idx, row.error)
                error_count += 1
                continue

            dedupe_key = (norm_key, chain_type)

            if dedupe_key in seen_in_batch:
                row.status = "duplicate"
                logger.warning("Row %d skipped: duplicate address '%s'", idx, addr_str)
                duplicate_count += 1
            else:
                row.status = "new"
                new_count += 1
                seen_in_batch.add(dedupe_key)

        return ImportPreview(
            format=chosen_format,
            rows=rows,
            new_count=new_count,
            duplicate_count=duplicate_count,
            error_count=error_count,
            default_group_id=default_group_id,
        )

    def _get_or_create_group(self, name: str) -> WalletGroup:
        """Find group by exact name or create a new one."""
        clean_name = name.strip()
        group = self.session.execute(
            select(WalletGroup).where(WalletGroup.name == clean_name)
        ).scalar_one_or_none()
        if group is None:
            group = WalletGroup(name=clean_name)
            self.session.add(group)
            self.session.flush()
        return group

    def _link_wallet_network(self, wallet_id: int, network_name: str) -> None:
        """Link wallet with network if valid and not already linked."""
        network = self.session.execute(
            select(Network).where(Network.name.ilike(network_name.strip()))
        ).scalar_one_or_none()
        if network is None:
            try:
                from app.config import load_config
                from app.core.network_manager import ensure_networks_from_config

                ensure_networks_from_config(self.session, load_config())
                network = self.session.execute(
                    select(Network).where(Network.name.ilike(network_name.strip()))
                ).scalar_one_or_none()
            except (AttributeError, ValueError, KeyError) as exc:
                logger.warning("Could not ensure network '%s' from config: %s", network_name, exc)

        if network is None:
            return

        existing_link = self.session.execute(
            select(WalletNetwork).where(
                WalletNetwork.wallet_id == wallet_id,
                WalletNetwork.network_id == network.id,
            )
        ).scalar_one_or_none()

        if existing_link is None:
            link = WalletNetwork(
                wallet_id=wallet_id,
                network_id=network.id,
                monitoring_status="active",
            )
            self.session.add(link)

    def apply(self, preview: ImportPreview, mode: str = "add_only") -> ImportReport:
        """Apply an ImportPreview to the database.

        mode:
          - "add_only": only adds new wallets; existing wallets are skipped.
          - "update": updates metadata of existing wallets.
        """
        added = 0
        updated = 0
        skipped = 0
        errors: list[ImportRow] = []
        applied_rows: list[ImportRow] = []

        wm = WalletManager(self.session)
        created_in_apply: set[tuple[str, str]] = set()

        for idx, row in enumerate(preview.rows, start=1):
            if row.status == "error":
                errors.append(row)
                skipped += 1
                applied_rows.append(row)
                logger.warning("Row %d skipped: %s", idx, row.error)
                continue

            addr_str = row.address.strip()
            if is_valid_evm_address(addr_str):
                chain_type = "evm"
                norm_addr = normalize_evm_address(addr_str)
                db_addr = norm_addr.lower()
            elif is_valid_solana_address(addr_str):
                chain_type = "solana"
                norm_addr = addr_str
                db_addr = addr_str
            else:
                row.status = "error"
                row.error = f"Invalid EVM or Solana address: '{row.address}'"
                errors.append(row)
                skipped += 1
                applied_rows.append(row)
                logger.warning("Row %d skipped: %s", idx, row.error)
                continue

            dedupe_key = (db_addr, chain_type)

            # Query existing wallet in DB
            existing = self.session.execute(
                select(Wallet).where(
                    Wallet.address == db_addr,
                    Wallet.chain_type == chain_type,
                )
            ).scalar_one_or_none()

            if existing is not None:
                if mode == "update":
                    update_kwargs: dict[str, Any] = {}
                    if row.name:
                        update_kwargs["name"] = row.name
                    if row.group:
                        grp = self._get_or_create_group(row.group)
                        update_kwargs["group_id"] = grp.id
                    if row.tags:
                        update_kwargs["tags"] = row.tags

                    if update_kwargs:
                        wm.update_wallet(existing.id, **update_kwargs)

                    if row.network:
                        self._link_wallet_network(existing.id, row.network)

                    row.status = "updated"
                    updated += 1
                else:
                    row.status = "skipped"
                    skipped += 1
                    logger.warning("Row %d skipped: wallet '%s' already exists (mode=add_only)", idx, addr_str)
                applied_rows.append(row)
            else:
                if dedupe_key in created_in_apply or row.status == "duplicate":
                    row.status = "skipped"
                    skipped += 1
                    logger.warning("Row %d skipped: duplicate wallet '%s'", idx, addr_str)
                    applied_rows.append(row)
                else:
                    group_id = None
                    if row.group:
                        grp = self._get_or_create_group(row.group)
                        group_id = grp.id
                    elif preview.default_group_id:
                        group_id = preview.default_group_id

                    wallet = wm.create_wallet(
                        address=norm_addr,
                        name=row.name,
                        chain_type=chain_type,
                        group_id=group_id,
                        tags=row.tags,
                    )
                    if row.network:
                        self._link_wallet_network(wallet.id, row.network)

                    created_in_apply.add(dedupe_key)
                    row.status = "added"
                    added += 1
                    applied_rows.append(row)

        self.session.flush()
        return ImportReport(
            added=added,
            updated=updated,
            skipped=skipped,
            errors=errors,
            rows=applied_rows,
        )
