"""LiveKit Service - Gestisce room e token per video call."""

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from livekit import api

from config.logging_config import logger
from core.interfaces.service import BaseService
from ui.secrets_manager import secrets_manager


@dataclass
class CallSession:
    """Rappresenta una sessione di chiamata attiva."""

    room_name: str
    participant_token: str
    agent_token: str
    user_id: str
    agent_id: str
    created_at: str
    ws_url: str

    def json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> "CallSession":
        return cls(**json.loads(data))


class LiveKitService(BaseService):
    """Gestisce le room LiveKit e i token."""

    name = "livekit"

    # TTL settings
    SESSION_BASE_TTL = 1800  # 30 minuti
    HEARTBEAT_EXTENSION = 300  # 5 minuti

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key: str = ""
        self.api_secret: str = ""
        self.ws_url: str = ""
        self._sessions: dict[str, CallSession] = {}
        self._redis = None  # Optional Redis for persistence
        self._worker_process = None
        self._watchdog_task = None
        self._worker_restarts = 0

    async def initialize(self) -> None:
        """Initialize LiveKit service."""
        self.api_key = secrets_manager.get_plain("LIVEKIT_API_KEY")
        self.api_secret = secrets_manager.get_plain("LIVEKIT_API_SECRET")
        self.ws_url = self.config.get("ws_url", "")

        if not self.api_key or not self.api_secret:
            logger.warning("LIVEKIT_API_KEY/SECRET not configured - LiveKit disabled")
            return

        if not self.ws_url:
            logger.warning("LiveKit ws_url not configured")
            return

        # Try to connect to Redis if configured
        redis_url = self.config.get("redis_url")
        if redis_url:
            try:
                import redis.asyncio as redis

                self._redis = redis.from_url(redis_url)
                await self._redis.ping()
                logger.info("LiveKit service connected to Redis")
                # Recover sessions on startup
                await self._recover_sessions()
            except Exception as e:
                logger.warning(f"Redis not available, using in-memory sessions: {e}")
                self._redis = None

        logger.info(f"LiveKit service initialized with URL: {self.ws_url}")

        # Start the voice agent worker
        await self._start_worker()

        # Start watchdog to monitor worker health
        self._watchdog_task = asyncio.create_task(self._worker_watchdog())

    async def _start_worker(self) -> None:
        """Start the LiveKit agent worker process."""
        import os as os_module
        import subprocess

        worker_path = Path(__file__).parent / "worker.py"
        if not worker_path.exists():
            logger.warning(f"Worker script not found: {worker_path}")
            return

        # Get OpenAI key for the worker (needed for STT/TTS even with GridBear LLM)
        openai_key = secrets_manager.get_plain("OPENAI_API_KEY")
        if not openai_key:
            logger.warning("OPENAI_API_KEY not set - worker STT/TTS may not work")

        env = os_module.environ.copy()
        env.update(
            {
                "LIVEKIT_URL": self.ws_url,
                "LIVEKIT_API_KEY": self.api_key,
                "LIVEKIT_API_SECRET": self.api_secret,
                "OPENAI_API_KEY": openai_key,
                "AGENT_NAME": self.config.get("agent_name", "My Agent"),
                "TTS_VOICE": self.config.get("tts_voice", "nova"),
                # LLM bridge via internal API on port 8000
                "GRIDBEAR_LLM_ENABLED": "1",
                "GRIDBEAR_LLM_PORT": "8000",
            }
        )

        if not openai_key:
            logger.warning("No OpenAI key - worker STT/TTS will not work")

        try:
            # Log worker output to file for debugging
            log_path = Path("/app/data/livekit_worker.log")
            log_file = open(log_path, "w")
            self._worker_process = subprocess.Popen(
                ["python3", "-u", str(worker_path), "start"],
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            self._worker_log_file = log_file
            logger.info(
                f"LiveKit worker started with PID {self._worker_process.pid}, logs at {log_path}"
            )
        except Exception as e:
            logger.error(f"Failed to start LiveKit worker: {e}")

    async def _worker_watchdog(self) -> None:
        """Monitor worker process and restart if crashed."""
        MAX_RESTARTS = 5
        CHECK_INTERVAL = 30  # seconds

        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            if not self._worker_process:
                continue
            retcode = self._worker_process.poll()
            if retcode is not None:
                logger.warning(
                    f"LiveKit worker exited with code {retcode}, "
                    f"restarts={self._worker_restarts}/{MAX_RESTARTS}"
                )
                if self._worker_restarts >= MAX_RESTARTS:
                    logger.error("LiveKit worker max restarts reached, giving up")
                    break
                self._worker_restarts += 1
                if hasattr(self, "_worker_log_file") and self._worker_log_file:
                    self._worker_log_file.close()
                await self._start_worker()
                logger.info("LiveKit worker restarted")

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if self._watchdog_task:
            self._watchdog_task.cancel()
        if self._redis:
            await self._redis.close()
        if self._worker_process:
            self._worker_process.terminate()
        if hasattr(self, "_worker_log_file") and self._worker_log_file:
            self._worker_log_file.close()
        logger.info("LiveKit service shutdown")

    async def health_check(self) -> bool:
        """Check if service is healthy."""
        if not (self.api_key and self.api_secret and self.ws_url):
            return False
        if self._worker_process and self._worker_process.poll() is not None:
            return False
        return True

    async def create_call(
        self,
        user_id: str,
        agent_id: str = "myagent",
        user_name: Optional[str] = None,
    ) -> CallSession:
        """Crea una nuova room per una chiamata.

        Args:
            user_id: ID dell'utente
            agent_id: ID dell'agente (default: myagent)
            user_name: Nome visualizzato dell'utente

        Returns:
            CallSession con token e info room
        """
        # Check for existing active call
        existing = await self.get_active_call_for_user(user_id)
        if existing:
            logger.info(f"User {user_id} already has active call: {existing.room_name}")
            return existing

        room_name = f"call-{user_id}-{int(time.time())}"
        user_name = user_name or user_id

        # Token per l'utente (TTL 1 ora)
        user_token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(user_id)
            .with_name(user_name)
            .with_ttl(timedelta(hours=1))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                )
            )
            .to_jwt()
        )

        # Token per l'agente (TTL 1 ora, admin)
        agent_token = (
            api.AccessToken(self.api_key, self.api_secret)
            .with_identity(f"agent-{agent_id}")
            .with_name(agent_id.capitalize())
            .with_ttl(timedelta(hours=1))
            .with_grants(
                api.VideoGrants(
                    room_join=True,
                    room=room_name,
                    room_admin=True,
                )
            )
            .to_jwt()
        )

        session = CallSession(
            room_name=room_name,
            participant_token=user_token,
            agent_token=agent_token,
            user_id=user_id,
            agent_id=agent_id,
            created_at=datetime.now().isoformat(),
            ws_url=self.ws_url,
        )

        # Store session
        await self._store_session(session)

        logger.info(f"Created call session: {room_name} for user {user_id}")
        return session

    async def end_call(self, room_name: str) -> bool:
        """Termina una chiamata.

        Args:
            room_name: Nome della room da terminare

        Returns:
            True se terminata con successo
        """
        session = await self._get_session(room_name)
        if not session:
            logger.warning(f"Session not found: {room_name}")
            return False

        try:
            # Delete room via LiveKit API
            room_service = api.RoomService(self.ws_url, self.api_key, self.api_secret)
            await room_service.delete_room(api.DeleteRoomRequest(room=room_name))
        except Exception as e:
            logger.warning(f"Failed to delete room via API: {e}")

        # Remove from storage
        await self._delete_session(room_name)

        logger.info(f"Ended call session: {room_name}")
        return True

    async def get_active_call_for_user(self, user_id: str) -> Optional[CallSession]:
        """Get active call for a user if exists."""
        for session in await self._get_all_sessions():
            if session.user_id == user_id:
                return session
        return None

    async def list_active_calls(self) -> list[CallSession]:
        """Lista tutte le chiamate attive."""
        return await self._get_all_sessions()

    async def heartbeat(self, room_name: str) -> bool:
        """Estende TTL della sessione.

        Chiamare ogni ~2 minuti dalla room attiva.
        """
        if self._redis:
            session_key = f"livekit:session:{room_name}"
            data = await self._redis.get(session_key)
            if not data:
                return False
            await self._redis.expire(session_key, self.SESSION_BASE_TTL)
            # Also extend user index key to prevent duplicates
            try:
                session = CallSession.from_json(data)
                user_key = f"livekit:user:{session.user_id}"
                if await self._redis.exists(user_key):
                    await self._redis.expire(user_key, self.SESSION_BASE_TTL)
            except Exception:
                pass
            return True
        return room_name in self._sessions

    # Storage methods

    async def _store_session(self, session: CallSession) -> None:
        """Store session in Redis or memory."""
        if self._redis:
            await self._redis.setex(
                f"livekit:session:{session.room_name}",
                self.SESSION_BASE_TTL,
                session.json(),
            )
            # Index by user_id for lookup
            await self._redis.setex(
                f"livekit:user:{session.user_id}",
                self.SESSION_BASE_TTL,
                session.room_name,
            )
        else:
            self._sessions[session.room_name] = session

    async def _get_session(self, room_name: str) -> Optional[CallSession]:
        """Get session from Redis or memory."""
        if self._redis:
            data = await self._redis.get(f"livekit:session:{room_name}")
            if data:
                return CallSession.from_json(data)
            return None
        return self._sessions.get(room_name)

    async def _delete_session(self, room_name: str) -> None:
        """Delete session from Redis or memory."""
        session = await self._get_session(room_name)
        if self._redis:
            await self._redis.delete(f"livekit:session:{room_name}")
            if session:
                await self._redis.delete(f"livekit:user:{session.user_id}")
        elif room_name in self._sessions:
            del self._sessions[room_name]

    async def _get_all_sessions(self) -> list[CallSession]:
        """Get all active sessions."""
        if self._redis:
            keys = await self._redis.keys("livekit:session:*")
            sessions = []
            for key in keys:
                data = await self._redis.get(key)
                if data:
                    sessions.append(CallSession.from_json(data))
            return sessions
        return list(self._sessions.values())

    async def _recover_sessions(self) -> None:
        """Recover sessions from Redis on startup."""
        if not self._redis:
            return

        keys = await self._redis.keys("livekit:session:*")
        logger.info(f"Recovering {len(keys)} LiveKit sessions from Redis")

        for key in keys:
            data = await self._redis.get(key)
            if data:
                session = CallSession.from_json(data)
                # Verify room still exists on LiveKit
                # For now, just log - could add verification later
                logger.debug(f"Recovered session: {session.room_name}")
