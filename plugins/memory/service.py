"""Memory Service Plugin.

Structured semantic memory using PostgreSQL pgvector and sentence-transformers.

Memory Types (based on cognitive science terminology):
- Episodic Memory: Stores conversation history (what was said)
- Declarative Memory: Stores extracted facts and knowledge
"""

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

from config.logging_config import logger
from config.settings import (
    get_memory_group_user_ids,
    get_unified_user_id,
    get_user_memory_group_name,
)
from core.encryption import decrypt, encrypt, is_encrypted
from core.interfaces.service import BaseMemoryService

FACT_EXTRACTION_PROMPT = """Analyze this conversation and extract important facts that could be useful to remember in the future.

Conversation:
{conversation}

Extract facts such as:
- Information the user explicitly asks to remember
- Secret words, codes, passwords, PINs mentioned
- Personal preferences (colors, foods, hobbies, etc.)
- Information about projects, work, activities
- Names of people, places, important dates
- Any detail the user might want to retrieve in the future

Reply ONLY with the extracted facts, one per line, in concise form.
Example: "Secret word: pippo" or "Favorite color: blue"
If there are no useful facts to store, reply with "NO_FACT".
"""

# Trivial messages that don't need fact extraction (lowercase)
TRIVIAL_MESSAGES = {
    "ok",
    "va bene",
    "grazie",
    "ciao",
    "hey",
    "hi",
    "hello",
    "bye",
    "si",
    "sì",
    "no",
    "perfetto",
    "ottimo",
    "bene",
    "capito",
    "yes",
    "yeah",
    "yep",
    "nope",
    "thanks",
    "thx",
    "ty",
}

# Minimum message length for fact extraction
MIN_FACT_EXTRACTION_LENGTH = 15

# SQL table references
_EPISODIC_TABLE = '"memory"."episodic"'
_DECLARATIVE_TABLE = '"memory"."declarative"'


class MemoryService(BaseMemoryService):
    """Structured semantic memory service using PostgreSQL pgvector.

    Implements two types of memory:
    - Episodic: Conversation history (searchable semantically)
    - Declarative: Extracted facts and knowledge
    """

    name = "memory"

    def __init__(self, config: dict):
        super().__init__(config)
        self.embedding_model = config.get("embedding_model", "all-MiniLM-L6-v2")
        self._embedder = None
        self._db = None
        # Shared executor for CPU-bound embedding computation
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="memory_")
        # Weights for combining results from different memory types
        self.episodic_weight = config.get("episodic_weight", 0.4)
        self.declarative_weight = config.get("declarative_weight", 0.6)

    @staticmethod
    def _decrypt_field(value: str | None) -> str:
        """Decrypt a field value if encrypted, otherwise return as-is."""
        if not value:
            return value or ""
        return decrypt(value) if is_encrypted(value) else value

    async def initialize(self) -> None:
        """Initialize sentence-transformers and database connection."""
        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(self.embedding_model)
            logger.info("Sentence-transformers model %s loaded", self.embedding_model)

            from core.registry import get_database

            self._db = get_database()

            # Create HNSW indexes for vector similarity search
            # (ORM auto-migrate handles BTREE but not HNSW operator classes)
            async with self._db.acquire() as conn:
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_episodic_embedding "
                    f"ON {_EPISODIC_TABLE} USING hnsw (embedding vector_cosine_ops)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_declarative_embedding "
                    f"ON {_DECLARATIVE_TABLE} USING hnsw (embedding vector_cosine_ops)"
                )
                # Composite indexes for user + time browsing
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_episodic_user_created "
                    f"ON {_EPISODIC_TABLE} (user_id, created_at DESC)"
                )
                await conn.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_declarative_user_created "
                    f"ON {_DECLARATIVE_TABLE} (user_id, created_at DESC)"
                )

            # Log counts
            ep_row = await self._db.fetch_one(
                f"SELECT count(*) AS cnt FROM {_EPISODIC_TABLE}"
            )
            dc_row = await self._db.fetch_one(
                f"SELECT count(*) AS cnt FROM {_DECLARATIVE_TABLE}"
            )
            ep_count = ep_row["cnt"] if ep_row else 0
            dc_count = dc_row["cnt"] if dc_row else 0
            logger.info(
                "Memory service initialized: %d episodic, %d declarative memories",
                ep_count,
                dc_count,
            )
        except Exception as e:
            logger.error("Failed to initialize memory service: %s", e)
            self._embedder = None
            self._db = None

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if self._executor:
            self._executor.shutdown(wait=False)

    @property
    def enabled(self) -> bool:
        """Check if memory service is available."""
        return self._embedder is not None and self._db is not None

    def _get_embedding_sync(self, text: str) -> list[float]:
        """Get embedding synchronously (for use in executor)."""
        return self._embedder.encode(text).tolist()

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding asynchronously using executor."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor, self._get_embedding_sync, text
        )

    def _is_trivial_message(self, message: str) -> bool:
        """Check if message is too trivial for fact extraction."""
        if not message:
            return True
        clean = message.strip().lower()
        if len(clean) < MIN_FACT_EXTRACTION_LENGTH:
            return True
        if clean in TRIVIAL_MESSAGES:
            return True
        return False

    @staticmethod
    def _vec_str(embedding: list[float]) -> str:
        """Convert embedding list to pgvector string literal."""
        return "[" + ",".join(str(v) for v in embedding) + "]"

    # =========================================================================
    # EPISODIC MEMORY - Conversation history
    # =========================================================================

    async def add_episodic_memory(
        self,
        user_message: str,
        assistant_response: str,
        user_id: str,
        platform: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a conversation turn in episodic memory."""
        if not self.enabled:
            return

        try:
            memory_id = str(uuid.uuid4())

            # Truncate assistant response to avoid leaking raw tool results
            assistant_preview = assistant_response[:300] if assistant_response else ""

            # Combine user and assistant for embedding (captures the interaction)
            content = f"User: {user_message}\nAssistant: {assistant_preview}"
            if len(content) > 2000:
                content = content[:2000] + "..."

            embedding = await self._get_embedding(content)
            vec = self._vec_str(embedding)

            mem_metadata = {
                "memory_type": "episodic",
            }
            if metadata:
                mem_metadata.update(metadata)

            user_msg_preview = user_message[:200] if user_message else ""

            await self._db.execute(
                f"INSERT INTO {_EPISODIC_TABLE} "
                "(id, user_id, platform, document, embedding, memory_type, "
                "user_message_preview, metadata) "
                "VALUES (%s, %s, %s, %s, %s::vector, %s, %s, %s)",
                (
                    memory_id,
                    user_id,
                    platform,
                    encrypt(content),
                    vec,
                    "episodic",
                    encrypt(user_msg_preview) if user_msg_preview else "",
                    json.dumps(mem_metadata),
                ),
            )
            logger.debug(
                "Added episodic memory for %s: %s...", user_id, user_message[:50]
            )
        except Exception as e:
            logger.error("Failed to add episodic memory: %s", e)

    def add_episodic_memory_sync(
        self,
        user_message: str,
        assistant_response: str,
        platform: str,
        username: str,
        metadata: dict | None = None,
    ) -> None:
        """Synchronous wrapper for add_episodic_memory."""
        if not self.enabled:
            return

        user_id = get_unified_user_id(platform, username)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self.add_episodic_memory(
                        user_message, assistant_response, user_id, platform, metadata
                    )
                )
            else:
                loop.run_until_complete(
                    self.add_episodic_memory(
                        user_message, assistant_response, user_id, platform, metadata
                    )
                )
        except RuntimeError:
            asyncio.run(
                self.add_episodic_memory(
                    user_message, assistant_response, user_id, platform, metadata
                )
            )

    async def search_episodic(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Search episodic memory for relevant past conversations."""
        if not self.enabled:
            return []

        group_user_ids = get_memory_group_user_ids(user_id)
        group_name = get_user_memory_group_name(user_id)
        if group_name:
            group_user_ids = list(group_user_ids) + [f"__group__:{group_name}"]

        try:
            query_embedding = await self._get_embedding(query)
            vec = self._vec_str(query_embedding)

            rows = await self._db.fetch_all(
                f"SELECT id, document, user_id, metadata, created_at, "
                f"1 - (embedding <=> %s::vector) AS relevance "
                f"FROM {_EPISODIC_TABLE} "
                "WHERE user_id = ANY(%s::text[]) "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (vec, list(group_user_ids), vec, limit),
            )

            return [
                {
                    "id": r["id"],
                    "content": self._decrypt_field(r["document"]),
                    "relevance": float(r["relevance"]),
                    "memory_type": "episodic",
                    "metadata": r["metadata"] or {},
                    "user_id": r["user_id"],
                    "created_at": r["created_at"].isoformat()
                    if r["created_at"]
                    else "",
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to search episodic memory: %s", e)
            return []

    # =========================================================================
    # DECLARATIVE MEMORY - Facts and knowledge
    # =========================================================================

    async def _extract_facts_with_claude(self, conversation: str) -> list[str]:
        """Use Claude CLI to extract facts from conversation."""
        prompt = FACT_EXTRACTION_PROMPT.format(conversation=conversation)

        cmd = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            "haiku",
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            stdout_str = stdout.decode()
            if not stdout_str:
                logger.warning("Empty Claude response for fact extraction")
                return []

            try:
                response = json.loads(stdout_str)
                text = response.get("result", "")
            except json.JSONDecodeError:
                text = stdout_str

            if "NO_FACT" in text:
                return []

            facts = [
                line.strip()
                for line in text.strip().split("\n")
                if line.strip() and not line.strip().startswith("-")
            ]

            if not facts:
                facts = [
                    line.strip().lstrip("- ").strip()
                    for line in text.strip().split("\n")
                    if line.strip()
                ]

            return [f for f in facts if f and "NO_FACT" not in f]

        except asyncio.TimeoutError:
            logger.warning("Claude CLI timed out during fact extraction")
            return []
        except Exception as e:
            logger.error("Error extracting facts with Claude: %s", e)
            return []

    async def add_declarative_memory(
        self, content: str, user_id: str, metadata: dict | None = None
    ) -> None:
        """Store declarative memory after extracting facts from conversation."""
        if not self.enabled:
            return

        # Skip trivial messages - no useful facts to extract
        if self._is_trivial_message(content):
            logger.debug(
                "Skipping fact extraction for trivial message: %s", content[:30]
            )
            return

        facts = await self._extract_facts_with_claude(content)

        if not facts:
            logger.debug("No facts extracted for user %s", user_id)
            return

        for fact in facts:
            try:
                memory_id = str(uuid.uuid4())
                embedding = await self._get_embedding(fact)
                vec = self._vec_str(embedding)

                mem_metadata = {
                    "memory_type": "declarative",
                }
                if metadata:
                    mem_metadata.update(metadata)

                await self._db.execute(
                    f"INSERT INTO {_DECLARATIVE_TABLE} "
                    "(id, user_id, document, embedding, memory_type, metadata) "
                    "VALUES (%s, %s, %s, %s::vector, %s, %s)",
                    (
                        memory_id,
                        user_id,
                        encrypt(fact),
                        vec,
                        "declarative",
                        json.dumps(mem_metadata),
                    ),
                )
                logger.debug(
                    "Added declarative memory for %s: %s...", user_id, fact[:50]
                )
            except Exception as e:
                logger.error("Failed to add declarative memory: %s", e)

    # Alias for backward compatibility
    async def add_memory(
        self, content: str, user_id: str, metadata: dict | None = None
    ) -> None:
        """Alias for add_declarative_memory (backward compatibility)."""
        await self.add_declarative_memory(content, user_id, metadata)

    def add_declarative_memory_sync(
        self,
        content: str,
        platform: str,
        username: str,
        metadata: dict | None = None,
    ) -> None:
        """Synchronous wrapper for add_declarative_memory."""
        if not self.enabled:
            return

        user_id = get_unified_user_id(platform, username)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    self.add_declarative_memory(content, user_id, metadata)
                )
            else:
                loop.run_until_complete(
                    self.add_declarative_memory(content, user_id, metadata)
                )
        except RuntimeError:
            asyncio.run(self.add_declarative_memory(content, user_id, metadata))

    # Alias for backward compatibility
    def add_memory_sync(
        self,
        content: str,
        platform: str,
        username: str,
        metadata: dict | None = None,
    ) -> None:
        """Alias for add_declarative_memory_sync (backward compatibility)."""
        self.add_declarative_memory_sync(content, platform, username, metadata)

    async def search_declarative(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Search declarative memory for relevant facts."""
        if not self.enabled:
            return []

        group_user_ids = get_memory_group_user_ids(user_id)
        group_name = get_user_memory_group_name(user_id)
        if group_name:
            group_user_ids = list(group_user_ids) + [f"__group__:{group_name}"]

        try:
            query_embedding = await self._get_embedding(query)
            vec = self._vec_str(query_embedding)

            rows = await self._db.fetch_all(
                f"SELECT id, document, user_id, metadata, created_at, "
                f"1 - (embedding <=> %s::vector) AS relevance "
                f"FROM {_DECLARATIVE_TABLE} "
                "WHERE user_id = ANY(%s::text[]) "
                "ORDER BY embedding <=> %s::vector "
                "LIMIT %s",
                (vec, list(group_user_ids), vec, limit),
            )

            return [
                {
                    "id": r["id"],
                    "content": self._decrypt_field(r["document"]),
                    "relevance": float(r["relevance"]),
                    "memory_type": "declarative",
                    "metadata": r["metadata"] or {},
                    "user_id": r["user_id"],
                    "created_at": r["created_at"].isoformat()
                    if r["created_at"]
                    else "",
                }
                for r in rows
            ]
        except Exception as e:
            logger.error("Failed to search declarative memory: %s", e)
            return []

    # =========================================================================
    # COMBINED MEMORY SEARCH
    # =========================================================================

    async def get_relevant(
        self, query: str, user_id: str, limit: int = 5
    ) -> list[dict]:
        """Retrieve relevant memories from both episodic and declarative.

        Searches both memory types and combines results using weighted scoring.
        """
        if not self.enabled:
            return []

        # Search both memory types in parallel
        episodic_results, declarative_results = await asyncio.gather(
            self.search_episodic(query, user_id, limit),
            self.search_declarative(query, user_id, limit),
        )

        # Apply weights to scores
        for mem in episodic_results:
            mem["weighted_score"] = mem["relevance"] * self.episodic_weight

        for mem in declarative_results:
            mem["weighted_score"] = mem["relevance"] * self.declarative_weight

        # Combine and sort by weighted score
        all_memories = episodic_results + declarative_results
        all_memories.sort(key=lambda x: x["weighted_score"], reverse=True)

        # Filter out low-relevance memories to avoid context pollution
        all_memories = [m for m in all_memories if m.get("relevance", 0) >= 0.45]

        # Take top results
        top_memories = all_memories[:limit]

        episodic_count = sum(
            1 for m in top_memories if m.get("memory_type") == "episodic"
        )
        declarative_count = sum(
            1 for m in top_memories if m.get("memory_type") == "declarative"
        )

        logger.debug(
            "Found %d relevant memories for %s (%d episodic, %d declarative)",
            len(top_memories),
            user_id,
            episodic_count,
            declarative_count,
        )

        return top_memories

    def get_relevant_memories(
        self,
        query: str,
        platform: str,
        username: str,
        limit: int = 5,
    ) -> list[dict]:
        """Synchronous wrapper for get_relevant (backward compatibility)."""
        if not self.enabled:
            return []

        user_id = get_unified_user_id(platform, username)

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, self.get_relevant(query, user_id, limit)
                    )
                    return future.result()
            else:
                return loop.run_until_complete(self.get_relevant(query, user_id, limit))
        except RuntimeError:
            return asyncio.run(self.get_relevant(query, user_id, limit))

    async def delete_memory(
        self, memory_id: str, memory_type: str | None = None
    ) -> bool:
        """Delete a specific memory by ID."""
        if not self.enabled:
            return False

        deleted = False
        try:
            if memory_type in (None, "episodic"):
                try:
                    row = await self._db.fetch_one(
                        f"DELETE FROM {_EPISODIC_TABLE} WHERE id = %s RETURNING id",
                        (memory_id,),
                    )
                    if row:
                        deleted = True
                except Exception:
                    pass

            if memory_type in (None, "declarative"):
                try:
                    row = await self._db.fetch_one(
                        f"DELETE FROM {_DECLARATIVE_TABLE} WHERE id = %s RETURNING id",
                        (memory_id,),
                    )
                    if row:
                        deleted = True
                except Exception:
                    pass

            if deleted:
                logger.debug("Deleted memory %s", memory_id)
            return deleted
        except Exception as e:
            logger.error("Failed to delete memory: %s", e)
            return False

    def get_all_memories(
        self,
        platform: str,
        username: str,
        memory_type: str | None = None,
    ) -> list[dict]:
        """Get all memories for a user."""
        if not self.enabled:
            return []

        user_id = get_unified_user_id(platform, username)

        try:
            db = self._db
            memories = []

            tables = []
            if memory_type in (None, "episodic"):
                tables.append(("episodic", _EPISODIC_TABLE))
            if memory_type in (None, "declarative"):
                tables.append(("declarative", _DECLARATIVE_TABLE))

            for mem_type, table in tables:
                with db.acquire_sync() as conn:
                    rows = conn.execute(
                        f"SELECT id, document, user_id, metadata, created_at, "
                        f"user_message_preview "
                        f"FROM {table} WHERE user_id = %s "
                        f"ORDER BY created_at DESC",
                        (user_id,),
                    ).fetchall()

                for row in rows:
                    meta = row["metadata"] or {}
                    memories.append(
                        {
                            "id": row["id"],
                            "content": self._decrypt_field(row["document"]),
                            "memory_type": mem_type,
                            "metadata": meta,
                            "created_at": row["created_at"].isoformat()
                            if row["created_at"]
                            else "",
                        }
                    )

            return memories
        except Exception as e:
            logger.error("Failed to get all memories: %s", e)
            return []

    def clear_user_memories(
        self,
        platform: str,
        username: str,
        memory_type: str | None = None,
    ) -> None:
        """Clear memories for a user."""
        if not self.enabled:
            return

        user_id = get_unified_user_id(platform, username)
        total_cleared = 0

        try:
            tables = []
            if memory_type in (None, "episodic"):
                tables.append(("episodic", _EPISODIC_TABLE))
            if memory_type in (None, "declarative"):
                tables.append(("declarative", _DECLARATIVE_TABLE))

            for mem_type, table in tables:
                with self._db.acquire_sync() as conn:
                    result = conn.execute(
                        f"DELETE FROM {table} WHERE user_id = %s",
                        (user_id,),
                    )
                    total_cleared += result.rowcount
                    conn.commit()

            if total_cleared > 0:
                logger.info("Cleared %d memories for user %s", total_cleared, user_id)
        except Exception as e:
            logger.error("Failed to clear user memories: %s", e)

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_memory_stats(
        self, platform: str | None = None, username: str | None = None
    ) -> dict:
        """Get memory statistics."""
        if not self.enabled:
            return {"episodic": 0, "declarative": 0, "total": 0}

        try:
            with self._db.acquire_sync() as conn:
                if platform and username:
                    user_id = get_unified_user_id(platform, username)
                    ep_row = conn.execute(
                        f"SELECT count(*) AS cnt FROM {_EPISODIC_TABLE} "
                        "WHERE user_id = %s",
                        (user_id,),
                    ).fetchone()
                    dc_row = conn.execute(
                        f"SELECT count(*) AS cnt FROM {_DECLARATIVE_TABLE} "
                        "WHERE user_id = %s",
                        (user_id,),
                    ).fetchone()
                else:
                    ep_row = conn.execute(
                        f"SELECT count(*) AS cnt FROM {_EPISODIC_TABLE}"
                    ).fetchone()
                    dc_row = conn.execute(
                        f"SELECT count(*) AS cnt FROM {_DECLARATIVE_TABLE}"
                    ).fetchone()

            episodic_count = ep_row["cnt"] if ep_row else 0
            declarative_count = dc_row["cnt"] if dc_row else 0

            return {
                "episodic": episodic_count,
                "declarative": declarative_count,
                "total": episodic_count + declarative_count,
            }
        except Exception as e:
            logger.error("Failed to get memory stats: %s", e)
            return {"episodic": 0, "declarative": 0, "total": 0}

    # =========================================================================
    # ADMIN HELPERS (used by ui/routes/memory.py)
    # =========================================================================

    async def get_all_memories_admin(
        self, user_id: str | None = None, memory_type: str | None = None
    ) -> list[dict]:
        """Get all memories for admin browsing (optionally filtered)."""
        if not self.enabled:
            return []

        memories = []
        tables = []
        if memory_type in (None, "episodic"):
            tables.append(("episodic", _EPISODIC_TABLE))
        if memory_type in (None, "declarative"):
            tables.append(("declarative", _DECLARATIVE_TABLE))

        for mem_type, table in tables:
            try:
                if user_id:
                    rows = await self._db.fetch_all(
                        f"SELECT id, document, user_id, metadata, created_at "
                        f"FROM {table} WHERE user_id = %s "
                        f"ORDER BY created_at DESC",
                        (user_id,),
                    )
                else:
                    rows = await self._db.fetch_all(
                        f"SELECT id, document, user_id, metadata, created_at "
                        f"FROM {table} ORDER BY created_at DESC"
                    )

                for row in rows:
                    meta = row["metadata"] or {}
                    memories.append(
                        {
                            "id": row["id"],
                            "content": self._decrypt_field(row["document"]),
                            "memory_type": mem_type,
                            "metadata": meta,
                            "created_at": row["created_at"].isoformat()
                            if row["created_at"]
                            else "",
                            "user_id": row["user_id"],
                        }
                    )
            except Exception:
                pass

        # Sort by created_at descending
        memories.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return memories

    async def search_all_memories(
        self, query: str, memory_type: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Search across all users (admin use). No user_id filter."""
        if not self.enabled:
            return []

        try:
            query_embedding = await self._get_embedding(query)
            vec = self._vec_str(query_embedding)

            results = []
            tables = []
            if memory_type in (None, "episodic"):
                tables.append(("episodic", _EPISODIC_TABLE))
            if memory_type in (None, "declarative"):
                tables.append(("declarative", _DECLARATIVE_TABLE))

            for mem_type, table in tables:
                rows = await self._db.fetch_all(
                    f"SELECT id, document, user_id, metadata, created_at, "
                    f"1 - (embedding <=> %s::vector) AS relevance "
                    f"FROM {table} "
                    f"ORDER BY embedding <=> %s::vector "
                    f"LIMIT %s",
                    (vec, vec, limit),
                )

                for r in rows:
                    meta = r["metadata"] or {}
                    results.append(
                        {
                            "id": r["id"],
                            "content": self._decrypt_field(r["document"]),
                            "relevance": float(r["relevance"]),
                            "memory_type": mem_type,
                            "metadata": meta,
                            "user_id": r["user_id"],
                            "created_at": r["created_at"].isoformat()
                            if r["created_at"]
                            else "",
                        }
                    )

            results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
            return results[:limit]
        except Exception:
            return []

    # =========================================================================
    # MEMORY CLEANUP
    # =========================================================================

    async def clear_memories(self, mode: str) -> int:
        """Clear memories based on mode.

        Args:
            mode: Cleanup mode
                - 'all': Clear all memories
                - 'old': Clear memories older than 30 days
                - 'episodic': Clear only episodic memories
                - 'facts': Clear only declarative memories
                - 'duplicates': Remove duplicate/similar memories

        Returns:
            Number of memories removed

        Raises:
            ValueError: If mode is invalid
        """
        if not self.enabled:
            return 0

        valid_modes = ["all", "old", "episodic", "facts", "duplicates"]
        if mode not in valid_modes:
            raise ValueError(f"Modo non valido. Usa: {', '.join(valid_modes)}")

        count = 0

        try:
            if mode == "all":
                for table in [_EPISODIC_TABLE, _DECLARATIVE_TABLE]:
                    row = await self._db.fetch_one(
                        f"WITH deleted AS (DELETE FROM {table} RETURNING 1) "
                        "SELECT count(*) AS cnt FROM deleted"
                    )
                    count += row["cnt"] if row else 0

            elif mode == "old":
                for table in [_EPISODIC_TABLE, _DECLARATIVE_TABLE]:
                    row = await self._db.fetch_one(
                        f"WITH deleted AS ("
                        f"  DELETE FROM {table} "
                        f"  WHERE created_at < NOW() - INTERVAL '30 days' "
                        f"  RETURNING 1"
                        f") SELECT count(*) AS cnt FROM deleted"
                    )
                    count += row["cnt"] if row else 0

            elif mode == "episodic":
                row = await self._db.fetch_one(
                    f"WITH deleted AS (DELETE FROM {_EPISODIC_TABLE} RETURNING 1) "
                    "SELECT count(*) AS cnt FROM deleted"
                )
                count = row["cnt"] if row else 0

            elif mode == "facts":
                row = await self._db.fetch_one(
                    f"WITH deleted AS (DELETE FROM {_DECLARATIVE_TABLE} RETURNING 1) "
                    "SELECT count(*) AS cnt FROM deleted"
                )
                count = row["cnt"] if row else 0

            elif mode == "duplicates":
                # Decrypt-then-compare in Python (encrypted content has unique nonces)
                for table in [_EPISODIC_TABLE, _DECLARATIVE_TABLE]:
                    rows = await self._db.fetch_all(
                        f"SELECT id, document, created_at FROM {table} "
                        f"ORDER BY created_at"
                    )
                    seen = {}
                    dup_ids = []
                    for r in rows:
                        doc = self._decrypt_field(r["document"])
                        key = doc.lower().strip()
                        if key in seen:
                            dup_ids.append(r["id"])
                        else:
                            seen[key] = r["id"]
                    if dup_ids:
                        row = await self._db.fetch_one(
                            f"WITH deleted AS ("
                            f"  DELETE FROM {table} WHERE id = ANY(%s::text[]) "
                            f"  RETURNING 1"
                            f") SELECT count(*) AS cnt FROM deleted",
                            (dup_ids,),
                        )
                        count += row["cnt"] if row else 0

            logger.info("Cleared %d memories (mode: %s)", count, mode)
            return count

        except Exception as e:
            logger.error("Failed to clear memories: %s", e)
            raise
