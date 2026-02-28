#!/usr/bin/env python3
"""LiveKit Agent Worker - Voice assistant che partecipa alle call.

Usa livekit-agents 1.3+ API con AgentSession e Agent.
"""

import asyncio
import logging
import os
import sys

# Force stdout flush immediately
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from livekit.agents import Agent, AgentSession, JobContext, WorkerOptions, cli
from livekit.plugins import openai, silero

# Setup logging to stdout
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("livekit-worker")

# Configuration from environment
LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# GridBear LLM bridge settings
GRIDBEAR_LLM_ENABLED = os.environ.get("GRIDBEAR_LLM_ENABLED", "0") == "1"
GRIDBEAR_LLM_PORT = int(os.environ.get("GRIDBEAR_LLM_PORT", "0"))

# Agent configuration
AGENT_NAME = os.environ.get("AGENT_NAME", "My Agent")
SYSTEM_PROMPT = os.environ.get(
    "SYSTEM_PROMPT",
    """Sei un'assistente virtuale amichevole e competente.
Rispondi in italiano in modo naturale e conversazionale.
Sii concisa nelle risposte vocali - massimo 2-3 frasi per risposta.
Se non capisci qualcosa, chiedi gentilmente di ripetere.""",
)
TTS_VOICE = os.environ.get("TTS_VOICE", "nova")


def _create_llm(room_name: str = ""):
    """Create LLM instance based on configuration."""
    if GRIDBEAR_LLM_ENABLED and GRIDBEAR_LLM_PORT:
        from gridbear_llm import GridBearLLM

        logger.info(f"Using GridBear LLM proxy on port {GRIDBEAR_LLM_PORT}")
        return GridBearLLM(port=GRIDBEAR_LLM_PORT, room_name=room_name)
    else:
        logger.info("Using OpenAI LLM (gpt-4o)")
        return openai.LLM(model="gpt-4o")


async def entrypoint(ctx: JobContext):
    """Entry point per il worker LiveKit."""
    logger.info("Worker received job, connecting...")

    # Connect to the room first
    await ctx.connect()
    logger.info(f"Connected to room: {ctx.room.name}")

    # Shutdown when all non-agent participants leave
    shutdown_event = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_disconnected(participant, *args):
        human_participants = [
            p
            for p in ctx.room.remote_participants.values()
            if not p.identity.startswith("agent-")
        ]
        if not human_participants:
            logger.info(f"No human participants left in {ctx.room.name}, shutting down")
            shutdown_event.set()

    # Create LLM (GridBear proxy or OpenAI)
    llm_instance = _create_llm(room_name=ctx.room.name)

    # Create the AgentSession with all components
    session = AgentSession(
        vad=silero.VAD.load(),
        stt=openai.STT(language="it"),
        llm=llm_instance,
        tts=openai.TTS(voice=TTS_VOICE),
    )

    # Start the session with the agent instructions
    await session.start(
        room=ctx.room,
        agent=Agent(instructions=SYSTEM_PROMPT),
    )

    logger.info(f"AgentSession started in room {ctx.room.name}")

    # Generate initial greeting
    await session.generate_reply(
        instructions=f"Saluta l'utente dicendo che sei {AGENT_NAME} e chiedi come puoi aiutare."
    )

    # Wait for shutdown signal
    await shutdown_event.wait()
    logger.info(f"Shutting down session for room {ctx.room.name}")
    await session.aclose()
    ctx.shutdown()


def main():
    """Main entry point."""
    # OpenAI key is needed for STT/TTS even when using GridBear LLM
    if not OPENAI_API_KEY:
        if not GRIDBEAR_LLM_ENABLED:
            logger.error("OPENAI_API_KEY not set and GridBear LLM not enabled")
            return
        else:
            logger.warning("OPENAI_API_KEY not set - STT/TTS will not work")

    logger.info("Starting LiveKit Agent Worker...")
    logger.info(f"LIVEKIT_URL: {LIVEKIT_URL}")
    logger.info(f"AGENT_NAME: {AGENT_NAME}")
    logger.info(f"LLM mode: {'GridBear proxy' if GRIDBEAR_LLM_ENABLED else 'OpenAI'}")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
        )
    )


if __name__ == "__main__":
    main()
