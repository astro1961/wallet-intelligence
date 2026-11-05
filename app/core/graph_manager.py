"""Relationship graph manager for wallet interactions, inferences, and exports."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import networkx as nx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.database.models import Transaction, Wallet, WalletRelation
from app.utils.validators import normalize_evm_address

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_ALLOWED_CONFIDENCES: frozenset[str] = frozenset({"confirmed", "inferred", "unknown"})
_CONFIDENCE_PRIORITY: dict[str, int] = {
    "confirmed": 3,
    "inferred": 2,
    "unknown": 1,
}


def _format_address(wallet: Wallet) -> str:
    """Format and normalize EVM address to EIP-55 checksummed representation."""
    addr = wallet.address
    if getattr(wallet, "chain_type", "evm") == "evm":
        try:
            return normalize_evm_address(addr)
        except (ValueError, TypeError):
            return addr
    return addr


def _extract_address_and_normalize(wallet: Wallet | str | int) -> tuple[str, str]:
    """Extract raw address string and validate/normalize via normalize_evm_address."""
    if isinstance(wallet, Wallet):
        raw = wallet.address
    elif isinstance(wallet, str):
        raw = wallet
    else:
        raise TypeError(
            f"Wallet must be a Wallet instance or address string, got {type(wallet).__name__}"
        )
    normalized = normalize_evm_address(raw)
    return raw, normalized


class GraphManager:
    """Session-based manager for wallet relationships and NetworkX analysis."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def _resolve_wallet(self, wallet: Wallet | str | int) -> Wallet | None:
        """Resolve a wallet instance, address string, or ID to a Wallet record."""
        if isinstance(wallet, Wallet):
            return wallet
        if isinstance(wallet, int):
            return self.session.get(Wallet, wallet)
        if isinstance(wallet, str):
            # 1. Exact address match
            w = self.session.execute(
                select(Wallet).where(Wallet.address == wallet)
            ).scalar_one_or_none()
            if w is not None:
                return w
            # 2. Normalized EVM address or case-insensitive match
            try:
                norm = normalize_evm_address(wallet)
                norm_lower = norm.lower()
            except ValueError:
                norm_lower = wallet.strip().lower()
            return self.session.execute(
                select(Wallet).where(func.lower(Wallet.address) == norm_lower)
            ).scalar_one_or_none()
        return None

    def add_relation(
        self,
        from_wallet: Wallet | str | int,
        to_wallet: Wallet | str | int,
        relation_type: str,
        confidence: str = "inferred",
        notes: str | None = None,
    ) -> WalletRelation:
        """Add or retrieve a relationship between two wallets.

        Normalises both addresses via normalize_evm_address, rejects self-loops
        with ValueError, and is idempotent per (from, to, relation_type).
        """
        raw_from, norm_from = _extract_address_and_normalize(from_wallet)
        raw_to, norm_to = _extract_address_and_normalize(to_wallet)

        if norm_from.lower() == norm_to.lower():
            raise ValueError(f"Self-loop relation is not allowed: {norm_from}")

        if confidence not in _ALLOWED_CONFIDENCES:
            raise ValueError(
                f"Invalid confidence: {confidence!r}. Must be 'confirmed', 'inferred', or 'unknown'"
            )

        if not isinstance(relation_type, str) or not relation_type.strip():
            raise ValueError("relation_type must be a non-empty string")
        rel_type = relation_type.strip()

        # Resolve or create from_wallet
        w_from = self.session.execute(
            select(Wallet).where(func.lower(Wallet.address) == norm_from.lower())
        ).scalar_one_or_none()
        if w_from is None:
            if isinstance(from_wallet, Wallet):
                w_from = from_wallet
            else:
                w_from = Wallet(address=norm_from, address_raw=raw_from, chain_type="evm")
            self.session.add(w_from)
            self.session.flush()

        # Resolve or create to_wallet
        w_to = self.session.execute(
            select(Wallet).where(func.lower(Wallet.address) == norm_to.lower())
        ).scalar_one_or_none()
        if w_to is None:
            if isinstance(to_wallet, Wallet):
                w_to = to_wallet
            else:
                w_to = Wallet(address=norm_to, address_raw=raw_to, chain_type="evm")
            self.session.add(w_to)
            self.session.flush()

        # Check existing relation for idempotency per (from, to, relation_type)
        stmt = select(WalletRelation).where(
            WalletRelation.from_wallet_id == w_from.id,
            WalletRelation.to_wallet_id == w_to.id,
            WalletRelation.relation_type == rel_type,
        )
        existing = self.session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            return existing

        relation = WalletRelation(
            from_wallet_id=w_from.id,
            to_wallet_id=w_to.id,
            relation_type=rel_type,
            confidence=confidence,
            notes=notes,
        )
        self.session.add(relation)
        self.session.flush()
        return relation

    def infer_from_transactions(self) -> int:
        """Walk transactions between tracked wallets and materialize inferred edges.

        Materialises a relation_type='transaction', confidence='inferred' edge for
        each distinct counterparty pair. Returns the number of relations created.
        """
        wallets = self.session.execute(select(Wallet)).scalars().all()
        wallet_by_lower: dict[str, Wallet] = {
            w.address.lower(): w for w in wallets if w.address
        }

        txs = self.session.execute(
            select(Transaction).where(Transaction.to_address.is_not(None))
        ).scalars().all()

        existing_rels = self.session.execute(
            select(WalletRelation).where(WalletRelation.relation_type == "transaction")
        ).scalars().all()
        existing_pairs: set[frozenset[int]] = {
            frozenset((r.from_wallet_id, r.to_wallet_id)) for r in existing_rels
        }

        created = 0
        seen_in_run: set[frozenset[int]] = set()

        for tx in txs:
            if not tx.from_address or not tx.to_address:
                continue
            f_lower = tx.from_address.strip().lower()
            t_lower = tx.to_address.strip().lower()

            w_from = wallet_by_lower.get(f_lower)
            w_to = wallet_by_lower.get(t_lower)
            if w_from is None or w_to is None:
                continue
            if w_from.id == w_to.id:
                continue

            pair = frozenset((w_from.id, w_to.id))
            if pair in existing_pairs or pair in seen_in_run:
                continue
            seen_in_run.add(pair)

            rel = WalletRelation(
                from_wallet_id=w_from.id,
                to_wallet_id=w_to.id,
                relation_type="transaction",
                confidence="inferred",
                notes="Inferred from on-chain transaction history",
            )
            self.session.add(rel)
            created += 1

        if created > 0:
            self.session.flush()
        return created

    def neighbors(self, wallet: Wallet | str | int) -> list[dict[str, Any]]:
        """Return adjacent wallets for given wallet as a list of dicts.

        Each dict: {'address': str, 'name': str|None, 'relation_type': str, 'confidence': str}.
        """
        w = self._resolve_wallet(wallet)
        if w is None or w.id is None:
            return []

        target_id = w.id
        stmt = (
            select(WalletRelation)
            .options(
                joinedload(WalletRelation.from_wallet),
                joinedload(WalletRelation.to_wallet),
            )
            .where(
                or_(
                    WalletRelation.from_wallet_id == target_id,
                    WalletRelation.to_wallet_id == target_id,
                )
            )
        )
        relations = self.session.execute(stmt).scalars().all()

        # Group by neighbor wallet ID to ensure one dict per adjacent wallet
        neighbor_map: dict[int, tuple[Wallet, WalletRelation]] = {}
        for rel in relations:
            if rel.from_wallet_id == target_id:
                other = rel.to_wallet
                other_id = rel.to_wallet_id
            else:
                other = rel.from_wallet
                other_id = rel.from_wallet_id

            if other is None:
                continue

            if other_id not in neighbor_map:
                neighbor_map[other_id] = (other, rel)
            else:
                existing_rel = neighbor_map[other_id][1]
                curr_rank = _CONFIDENCE_PRIORITY.get(rel.confidence, 0)
                prev_rank = _CONFIDENCE_PRIORITY.get(existing_rel.confidence, 0)
                if curr_rank > prev_rank:
                    neighbor_map[other_id] = (other, rel)

        result: list[dict[str, Any]] = []
        for other, rel in neighbor_map.values():
            result.append({
                "address": _format_address(other),
                "name": other.name,
                "relation_type": rel.relation_type,
                "confidence": rel.confidence,
            })

        result.sort(key=lambda item: item["address"])
        return result

    def build_graph(self) -> nx.Graph:
        """Return an undirected NetworkX Graph.

        Nodes keyed by wallet address with 'name' attribute, edges carrying
        'relation_type' and 'confidence' attributes.
        """
        graph = nx.Graph()
        stmt = (
            select(WalletRelation)
            .options(
                joinedload(WalletRelation.from_wallet),
                joinedload(WalletRelation.to_wallet),
            )
        )
        relations = self.session.execute(stmt).scalars().all()

        for rel in relations:
            if rel.from_wallet is None or rel.to_wallet is None:
                continue
            u = _format_address(rel.from_wallet)
            v = _format_address(rel.to_wallet)

            if u not in graph:
                graph.add_node(u, name=rel.from_wallet.name)
            elif graph.nodes[u].get("name") is None and rel.from_wallet.name:
                graph.nodes[u]["name"] = rel.from_wallet.name

            if v not in graph:
                graph.add_node(v, name=rel.to_wallet.name)
            elif graph.nodes[v].get("name") is None and rel.to_wallet.name:
                graph.nodes[v]["name"] = rel.to_wallet.name

            if graph.has_edge(u, v):
                prev_conf = graph.edges[u, v].get("confidence", "unknown")
                curr_rank = _CONFIDENCE_PRIORITY.get(rel.confidence, 0)
                prev_rank = _CONFIDENCE_PRIORITY.get(prev_conf, 0)
                if curr_rank > prev_rank:
                    graph.edges[u, v]["relation_type"] = rel.relation_type
                    graph.edges[u, v]["confidence"] = rel.confidence
            else:
                graph.add_edge(
                    u,
                    v,
                    relation_type=rel.relation_type,
                    confidence=rel.confidence,
                )

        return graph

    def export_json(self) -> dict[str, list[dict[str, Any]]]:
        """Return JSON-serializable dict of nodes and edges.

        Format: {'nodes': [{'id': addr, 'name': ...}], 'edges': [{'source': ..., 'target': ..., 'relation_type': ..., 'confidence': ...}]}.
        """
        stmt = (
            select(WalletRelation)
            .options(
                joinedload(WalletRelation.from_wallet),
                joinedload(WalletRelation.to_wallet),
            )
        )
        relations = self.session.execute(stmt).scalars().all()

        nodes_map: dict[str, str | None] = {}
        edges_list: list[dict[str, Any]] = []
        seen_edge_keys: set[tuple[str, str, str]] = set()

        for rel in relations:
            if rel.from_wallet is None or rel.to_wallet is None:
                continue
            src = _format_address(rel.from_wallet)
            dst = _format_address(rel.to_wallet)

            if src not in nodes_map or (nodes_map[src] is None and rel.from_wallet.name):
                nodes_map[src] = rel.from_wallet.name
            if dst not in nodes_map or (nodes_map[dst] is None and rel.to_wallet.name):
                nodes_map[dst] = rel.to_wallet.name

            edge_key = (src, dst, rel.relation_type)
            if edge_key not in seen_edge_keys:
                seen_edge_keys.add(edge_key)
                edges_list.append({
                    "source": src,
                    "target": dst,
                    "relation_type": rel.relation_type,
                    "confidence": rel.confidence,
                })

        nodes_list = [
            {"id": addr, "name": name}
            for addr, name in sorted(nodes_map.items(), key=lambda x: x[0])
        ]
        return {"nodes": nodes_list, "edges": edges_list}
