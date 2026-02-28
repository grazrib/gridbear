"""Discord Channel Plugin.

Discord bot adapter implementing BaseChannel interface.
"""

import asyncio
import contextlib
import re
import time
import uuid
from pathlib import Path
from typing import List

import discord
from discord.ext import commands

from config.logging_config import logger
from config.settings import (
    TRIGGER_WORD,
    get_unified_user_id,
    get_user_locale,
)
from core.i18n import make_translator, set_language
from core.interfaces.channel import BaseChannel, Message, UserInfo
from sessions.context_builder import UserInfo as ContextUserInfo
from ui.secrets_manager import secrets_manager

# Create translator for this plugin
_ = make_translator("discord")

DISCORD_MAX_MESSAGE_LENGTH = 2000

# Day of week names for cron parsing
DAYS_OF_WEEK = {
    "0": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
    "7": "Sunday",
    "sun": "Sunday",
    "mon": "Monday",
    "tue": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
}

DAYS_IT = {
    "Sunday": "domenica",
    "Monday": "lunedì",
    "Tuesday": "martedì",
    "Wednesday": "mercoledì",
    "Thursday": "giovedì",
    "Friday": "venerdì",
    "Saturday": "sabato",
}


def cron_to_human(cron: str, locale: str = "en") -> str:
    """Convert cron expression to human-readable text."""
    try:
        parts = cron.split()
        if len(parts) < 5:
            return cron
        minute, hour, day, month, dow = parts[:5]
        time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
        if day == "*" and month == "*" and dow == "*":
            if locale == "it":
                return f"Ogni giorno alle {time_str}"
            return f"Every day at {time_str}"
        elif dow != "*" and day == "*":
            day_name = DAYS_OF_WEEK.get(dow.lower(), dow)
            if locale == "it":
                day_name = DAYS_IT.get(day_name, day_name)
                return f"Ogni {day_name} alle {time_str}"
            return f"Every {day_name} at {time_str}"
        elif day != "*" and month == "*":
            if locale == "it":
                return f"Il giorno {day} di ogni mese alle {time_str}"
            return f"Day {day} of every month at {time_str}"
        else:
            if locale == "it":
                return f"Ricorrente alle {time_str}"
            return f"Recurring at {time_str}"
    except Exception:
        return cron


class DiscordChannel(BaseChannel):
    """Discord messaging channel."""

    platform = "discord"

    def __init__(self, config: dict):
        super().__init__(config)
        token_env = config.get("token_env", "DISCORD_TOKEN")
        self.token = secrets_manager.get_plain(token_env)
        self.command_prefix = config.get("command_prefix", "!")

        self._user_channels: dict[int, int] = {}
        self._user_usernames: dict[int, str] = {}
        self._active_tasks: dict[int, asyncio.Task] = {}

        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.dm_messages = True

        self.bot = commands.Bot(
            command_prefix=self.command_prefix,
            intents=intents,
            help_command=None,
        )
        self._setup_handlers()

    def _create_runner_callbacks(self, thinking_msg):
        """Create progress, error, tool, and stream callbacks for runner."""

        async def progress_callback(progress_message: str):
            try:
                await thinking_msg.edit(content=progress_message)
            except Exception as e:
                logger.warning(f"Failed to update progress message: {e}")

        async def error_callback(error_type: str, details: dict):
            logger.error(f"Runner error [{error_type}]: {details}")
            try:
                if error_type == "timeout":
                    timeout_secs = details.get("timeout_seconds", "?")
                    await thinking_msg.edit(
                        content=f"Timeout after {timeout_secs} seconds. "
                        "The request was too complex. Try simplifying."
                    )
                elif error_type == "exception":
                    error_msg = details.get("error", "Unknown error")
                    await thinking_msg.edit(
                        content=f"An error occurred: {error_msg[:100]}"
                    )
                elif error_type == "retries_exhausted":
                    await thinking_msg.edit(
                        content="All retries failed. Please try again later."
                    )
            except Exception as e:
                logger.warning(f"Failed to send error notification: {e}")

        async def tool_callback(tool_name: str, tool_input: dict):
            try:
                if tool_input.get("_grouped"):
                    status_text = tool_name
                else:
                    from core.tool_display import format_tool_status

                    status_text = format_tool_status(tool_name, tool_input)
                await thinking_msg.edit(content=status_text)
            except Exception as e:
                logger.debug(f"Failed to update tool status: {e}")

        # Streaming callback: rate-limited edit of thinking_msg with progressive text
        _stream_last_edit = 0.0
        STREAM_EDIT_INTERVAL = 1.5  # Discord is less restrictive than Telegram

        async def stream_callback(text: str):
            """Show progressive text in thinking message (rate-limited)."""
            nonlocal _stream_last_edit
            now = time.time()
            if now - _stream_last_edit < STREAM_EDIT_INTERVAL:
                return
            _stream_last_edit = now
            max_len = DISCORD_MAX_MESSAGE_LENGTH - 20
            display = text[:max_len] + "\n\n*...*" if len(text) > max_len else text
            try:
                await thinking_msg.edit(content=display)
            except Exception:
                pass

        return progress_callback, error_callback, tool_callback, stream_callback

    def _set_user_language(self, username: str | None) -> None:
        """Set translation language based on user's locale preference."""
        if username:
            unified_id = get_unified_user_id("discord", username)
            locale = get_user_locale(unified_id)
            set_language(locale)
        else:
            set_language("en")

    def _cache_username(self, user_id: int, username: str | None):
        """Cache username for scheduled tasks."""
        if username:
            self._user_usernames[user_id] = username.lower()

    async def initialize(self) -> None:
        """Initialize Discord bot."""
        if not self.token:
            logger.warning("Discord token not configured")
            return
        logger.info("Discord channel initialized")

    def _setup_handlers(self) -> None:
        @self.bot.event
        async def on_ready():
            logger.info(f"Discord bot logged in as {self.bot.user}")

        @self.bot.command(name="reset")
        async def cmd_reset(ctx: commands.Context):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            if not self.is_authorized(user_id, username):
                await ctx.send(_("Not authorized."))
                return

            self._cache_username(user_id, username)

            sessions_service = (
                self._plugin_manager.get_service("sessions")
                if self._plugin_manager
                else None
            )
            attachments_service = (
                self._plugin_manager.get_service("attachments")
                if self._plugin_manager
                else None
            )

            if sessions_service:
                session_ids = await sessions_service.clear_session(user_id, "discord")
                if attachments_service:
                    for sid in session_ids:
                        await attachments_service.cleanup_session(sid)

            await ctx.send(_("Session reset. Start a new chat!"))

        @self.bot.command(name="help")
        async def cmd_help(ctx: commands.Context):
            username = ctx.author.name
            self._set_user_language(username)

            await ctx.send(
                _(
                    "**Commands**\n\n"
                    "**Chat:**\n"
                    "`!gridbear <message>` - Talk to the assistant\n"
                    "`!reset` - Reset session\n"
                    "`!stop` - Stop current request\n\n"
                    "**Memory:**\n"
                    "`!memory` - Memory management\n\n"
                    "**Memos/Reminders:**\n"
                    "`!memo` - List memos\n"
                    "`!delmemo <id>` - Delete memo\n"
                    "`!delmemo all` - Delete all\n\n"
                    "**Creating memos:**\n"
                    '"remind me every Monday at 9 to X"\n'
                    '"in 30 minutes tell me Y"\n\n'
                    "You can also mention @bot, use the trigger word, "
                    "or send attachments (documents, images, voice)."
                )
            )

        @self.bot.command(name="gridbear")
        async def cmd_gridbear(ctx: commands.Context, *, message: str = ""):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            if not self.is_authorized(user_id, username):
                await ctx.send(_("Not authorized."))
                return

            self._cache_username(user_id, username)

            if not message:
                await ctx.send(_("Write a message after !gridbear"))
                return

            await self._process_request(ctx, message)

        @self.bot.command(name="memo")
        async def cmd_memo(ctx: commands.Context):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            if not self.is_authorized(user_id, username):
                await ctx.send(_("Not authorized."))
                return

            self._cache_username(user_id, username)

            if not self._task_scheduler:
                await ctx.send(_("Memo service not available."))
                return

            tasks = await self._task_scheduler.list_memos(user_id, "discord")
            if not tasks:
                await ctx.send(_("No memos."))
                return

            unified_id = get_unified_user_id("discord", username) if username else None
            locale = get_user_locale(unified_id) if unified_id else "en"

            lines = [_("**Your memos:**\n")]
            for t in tasks:
                status = "✅" if t["enabled"] else "⏸️"

                if t.get("schedule_type") == "cron" and t.get("cron"):
                    when = cron_to_human(t["cron"], locale)
                elif t.get("run_at"):
                    try:
                        from datetime import datetime

                        run_at = datetime.fromisoformat(t["run_at"])
                        when = run_at.strftime("%d/%m/%Y %H:%M")
                    except Exception:
                        when = t["run_at"]
                else:
                    when = t.get("description", "")

                title = t.get("prompt_title", "")
                content = t.get("prompt_content", "") or t.get("prompt", "")
                display_text = (
                    title
                    if title
                    else (content[:80] + "..." if len(content) > 80 else content)
                )

                lines.append(f"{status} **{t['id']}**: {display_text}")
                lines.append(f"   ⏰ {when}")
                if t.get("last_run"):
                    lines.append(f"   {_('Last run:')} {t['last_run'][:16]}")

            await ctx.send("\n".join(lines))

        @self.bot.command(name="delmemo")
        async def cmd_delmemo(ctx: commands.Context, task_id: str = None):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            if not self.is_authorized(user_id, username):
                await ctx.send(_("Not authorized."))
                return

            self._cache_username(user_id, username)

            if not self._task_scheduler:
                await ctx.send(_("Memo service not available."))
                return

            if not task_id:
                await ctx.send(_("Usage: /delmemo <id> or /delmemo all"))
                return

            if task_id.lower() == "all":
                memos = await self._task_scheduler.list_memos(user_id, "discord")
                count = 0
                for m in memos:
                    if await self._task_scheduler.delete_memo(m["id"], user_id):
                        count += 1
                await ctx.send(_("Deleted {count} memo(s).").format(count=count))
            else:
                try:
                    memo_id = int(task_id)
                    if await self._task_scheduler.delete_memo(memo_id, user_id):
                        await ctx.send(
                            _("Memo {memo_id} deleted.").format(memo_id=memo_id)
                        )
                    else:
                        await ctx.send(_("Memo not found."))
                except ValueError:
                    await ctx.send(_("Invalid ID."))

        @self.bot.command(name="memory")
        async def cmd_memory(ctx: commands.Context, *, args: str = ""):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            if not self.is_authorized(user_id, username):
                await ctx.send(_("Not authorized."))
                return

            self._cache_username(user_id, username)
            unified_id = get_unified_user_id("discord", username) if username else None

            memory_service = (
                self._plugin_manager.get_service("memory")
                if self._plugin_manager
                else None
            )
            if not memory_service or not memory_service.enabled:
                await ctx.send(_("Memory service not available."))
                return

            parts = args.split() if args else []
            if not parts:
                await self._memory_help(ctx)
                return

            subcommand = parts[0].lower()

            if subcommand == "help":
                await self._memory_help(ctx)
            elif subcommand == "stats":
                await self._memory_stats(ctx, memory_service, username)
            elif subcommand == "list":
                limit = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 5
                await self._memory_list(ctx, memory_service, username, limit)
            elif subcommand == "search":
                if len(parts) < 2:
                    await ctx.send(_("Usage: !memory search <query>"))
                    return
                query = " ".join(parts[1:])
                await self._memory_search(ctx, memory_service, unified_id, query)
            elif subcommand == "delete":
                if len(parts) < 2:
                    await ctx.send(_("Usage: !memory delete <id>"))
                    return
                await self._memory_delete(ctx, memory_service, parts[1])
            elif subcommand == "clear":
                if len(parts) < 2:
                    await ctx.send(
                        _(
                            "**Usage:** !memory clear <type>\n\n"
                            "**Types:** `all`, `episodic`, `facts`"
                        )
                    )
                    return
                await self._memory_clear(ctx, memory_service, username, parts[1])
            else:
                await self._memory_help(ctx)

        @self.bot.command(name="stop")
        async def cmd_stop(ctx: commands.Context):
            user_id = ctx.author.id
            username = ctx.author.name
            self._set_user_language(username)

            task = self._active_tasks.get(user_id)
            if not task or task.done():
                await ctx.send(_("No active request to stop."))
                return

            task.cancel()

            # Also cancel any async background tasks for this agent
            from core.mcp_gateway.server import get_task_manager

            task_manager = get_task_manager()
            if task_manager and self.agent_name:
                cancelled = task_manager.cancel_tasks_by_agent(self.agent_name)
                if cancelled:
                    logger.info(
                        "Cancelled %d async tasks for agent %s",
                        cancelled,
                        self.agent_name,
                    )

            await ctx.send(_("Stopping..."))

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return

            is_dm = isinstance(message.channel, discord.DMChannel)
            is_mentioned = self.bot.user in message.mentions
            has_trigger = TRIGGER_WORD in message.content.lower()

            if is_dm or is_mentioned or has_trigger:
                user_id = message.author.id
                username = message.author.name
                logger.debug(
                    f"Discord on_message: dm={is_dm}, mentioned={is_mentioned}, trigger={has_trigger}, user={username}, content={message.content[:50]!r}"
                )
                self._set_user_language(username)

                if not self.is_authorized(user_id, username):
                    await message.channel.send(_("Not authorized."))
                    await self.bot.process_commands(message)
                    return

                self._user_channels[user_id] = message.channel.id
                self._cache_username(user_id, username)

                content = message.content
                if is_mentioned:
                    content = content.replace(f"<@{self.bot.user.id}>", "").strip()

                if content.startswith(self.command_prefix) or content.startswith("/"):
                    logger.debug(
                        f"Discord: routing to command handler: {content[:30]!r}"
                    )
                    await self.bot.process_commands(message)
                    return

                try:
                    if message.attachments:
                        # Check if this is a voice message
                        is_voice = any(
                            a.content_type and a.content_type.startswith("audio/ogg")
                            for a in message.attachments
                        )
                        if is_voice and len(message.attachments) == 1:
                            await self._handle_voice(message)
                        else:
                            await self._handle_attachment(message, content)
                    elif content:
                        logger.debug(
                            f"Discord: calling _process_request with content={content[:50]!r}"
                        )
                        ctx = await self.bot.get_context(message)
                        await self._process_request(ctx, content)
                    else:
                        logger.debug(
                            "Discord: empty content after processing, skipping"
                        )
                except Exception as e:
                    logger.exception(f"Discord on_message error: {e}")
                    try:
                        await message.channel.send(f"Error: {str(e)[:100]}")
                    except Exception:
                        pass

            await self.bot.process_commands(message)

    async def start(self) -> None:
        """Start Discord bot."""
        if not self.token:
            logger.warning("Cannot start Discord: no token configured")
            return

        logger.info("Starting Discord bot...")
        await self.bot.start(self.token)

    async def stop(self) -> None:
        """Stop Discord bot."""
        await self.bot.close()
        logger.info("Discord bot stopped")

    async def send_message(
        self,
        user_id: int,
        text: str,
        attachments: list[str] | None = None,
    ) -> None:
        """Send message to a user."""
        channel_id = self._user_channels.get(user_id)
        if not channel_id:
            logger.warning(f"No channel stored for user {user_id}")
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"Channel {channel_id} not found")
            return

        formatted_text = self._convert_tables_to_code_blocks(text)
        chunks = self._split_message(formatted_text, DISCORD_MAX_MESSAGE_LENGTH)

        for chunk in chunks:
            await channel.send(chunk)

        if attachments:
            for attachment_path in attachments:
                path = Path(attachment_path)
                if path.exists():
                    await channel.send(file=discord.File(str(path)))

    async def get_user_info(self, user_id: int) -> UserInfo | None:
        """Get user information."""
        username = self._user_usernames.get(user_id)
        return UserInfo(
            user_id=user_id,
            username=username,
            display_name=username,
            platform="discord",
        )

    def _get_context_user_info(
        self, author: discord.User | discord.Member
    ) -> ContextUserInfo:
        """Extract user info from Discord author."""
        return ContextUserInfo(
            user_id=author.id,
            username=author.name,
            first_name=author.display_name,
            last_name=None,
            platform="discord",
        )

    # --- Memory command helpers ---

    async def _memory_help(self, ctx: commands.Context) -> None:
        """Show memory command help."""
        await ctx.send(
            _(
                "**Memory Management**\n\n"
                "**Commands:**\n"
                "`!memory stats` - Your memory statistics\n"
                "`!memory list [n]` - List last n memories (default 5)\n"
                "`!memory search <query>` - Semantic search\n"
                "`!memory delete <id>` - Delete a memory\n"
                "`!memory clear <type>` - Clear your memories\n\n"
                "**Clear types:** `all`, `episodic`, `facts`"
            )
        )

    async def _memory_stats(
        self, ctx: commands.Context, memory_service, username: str
    ) -> None:
        """Show memory statistics for user."""
        stats = memory_service.get_memory_stats("discord", username)
        await ctx.send(
            _(
                "**Your Memory Stats**\n\n"
                "Episodic: {episodic}\n"
                "Declarative: {declarative}\n"
                "Total: {total}"
            ).format(**stats)
        )

    async def _memory_list(
        self, ctx: commands.Context, memory_service, username: str, limit: int
    ) -> None:
        """List recent memories for user."""
        memories = memory_service.get_all_memories("discord", username)
        memories = memories[:limit]

        if not memories:
            await ctx.send(_("No memories found."))
            return

        lines = [_("**Your Recent Memories**\n")]
        for mem in memories:
            mem_type = "E" if mem.get("memory_type") == "episodic" else "D"
            content = mem.get("content", "")[:80]
            if len(mem.get("content", "")) > 80:
                content += "..."
            mem_id = mem.get("id", "")[:8]
            lines.append(f"`[{mem_type}] {mem_id}` {content}\n")

        await ctx.send("\n".join(lines))

    async def _memory_search(
        self, ctx: commands.Context, memory_service, unified_id: str, query: str
    ) -> None:
        """Search memories semantically."""
        results = await memory_service.get_relevant(query, unified_id, limit=5)

        if not results:
            await ctx.send(_("No matching memories found."))
            return

        lines = [_("**Search Results**\n")]
        for mem in results:
            mem_type = "E" if mem.get("memory_type") == "episodic" else "D"
            content = mem.get("content", "")[:80]
            if len(mem.get("content", "")) > 80:
                content += "..."
            relevance = int(mem.get("relevance", 0) * 100)
            lines.append(f"`[{mem_type}] {relevance}%` {content}\n")

        await ctx.send("\n".join(lines))

    async def _memory_delete(
        self, ctx: commands.Context, memory_service, memory_id: str
    ) -> None:
        """Delete a specific memory."""
        deleted = await memory_service.delete_memory(memory_id)
        if deleted:
            await ctx.send(_("Memory {id} deleted.").format(id=memory_id[:8]))
        else:
            await ctx.send(_("Memory not found."))

    async def _memory_clear(
        self,
        ctx: commands.Context,
        memory_service,
        username: str,
        mode: str,
    ) -> None:
        """Clear user's own memories by mode."""
        mode = mode.lower()
        type_map = {"all": None, "episodic": "episodic", "facts": "declarative"}
        if mode not in type_map:
            await ctx.send(_("Invalid type. Use: all, episodic, facts"))
            return
        try:
            memory_service.clear_user_memories(
                "discord",
                username,
                memory_type=type_map[mode],
            )
            await ctx.send(_("Memories cleared (type: {mode}).").format(mode=mode))
        except Exception as e:
            logger.exception(f"Error clearing memory: {e}")
            await ctx.send(f"Error: {e}")

    # --- Voice handling ---

    async def _handle_voice(self, message: discord.Message) -> None:
        """Handle voice messages: transcribe, process, and respond with voice."""
        user_id = message.author.id
        username = message.author.name
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await message.channel.send(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        # Reject if already processing
        if user_id in self._active_tasks and not self._active_tasks[user_id].done():
            await message.channel.send(
                _("A request is already running. Use !stop to cancel it.")
            )
            return

        attachment = message.attachments[0]
        voice_path = Path(f"/tmp/gridbear_voice_{uuid.uuid4().hex}.ogg")

        try:
            await attachment.save(voice_path)

            voice_service = (
                self._plugin_manager.get_service("transcription")
                if self._plugin_manager
                else None
            )
            if not voice_service:
                await message.channel.send(_("Voice service not available."))
                return

            transcribing_msg = await message.channel.send(_("Transcribing..."))
            text = await voice_service.transcribe(str(voice_path))
            await transcribing_msg.delete()

            if not text:
                await message.channel.send(_("Could not transcribe voice message."))
                return

            await message.channel.send(f"*{text}*")

            is_dm = isinstance(message.channel, discord.DMChannel)

            if not self._message_handler:
                return

            msg = Message(
                user_id=user_id,
                username=username,
                text=text,
                platform="discord",
                respond_with_voice=True,
                is_group_chat=not is_dm,
            )
            user_info = UserInfo(
                user_id=user_id,
                username=username,
                display_name=message.author.display_name,
                platform="discord",
            )

            thinking_msg = await message.channel.send(_("Thinking..."))
            progress_cb, error_cb, tool_cb, stream_cb = self._create_runner_callbacks(
                thinking_msg
            )

            try:
                response_text = await self._message_handler(
                    msg,
                    user_info,
                    progress_callback=progress_cb,
                    error_callback=error_cb,
                    tool_callback=tool_cb,
                    stream_callback=stream_cb,
                )
                await thinking_msg.delete()

                # Try to respond with voice
                tts_service = (
                    self._plugin_manager.get_service("tts")
                    if self._plugin_manager
                    else None
                )
                if tts_service and response_text.strip():
                    agent_ctx = self.get_agent_context()
                    voice_config = agent_ctx.get("voice", {})
                    voice_id = voice_config.get("voice_id")

                    unified_id = (
                        get_unified_user_id("discord", username) if username else None
                    )
                    locale = get_user_locale(unified_id) if unified_id else "en"

                    clean_text = response_text
                    clean_text = self._remove_file_tags(clean_text)

                    if clean_text.strip():
                        try:
                            if voice_id:
                                audio_path = await tts_service.synthesize(
                                    clean_text.strip(), voice=voice_id
                                )
                            else:
                                audio_path = await tts_service.synthesize(
                                    clean_text.strip(), locale=locale
                                )
                            await message.channel.send(file=discord.File(audio_path))
                            Path(audio_path).unlink(missing_ok=True)
                        except Exception as e:
                            logger.warning(f"TTS failed, falling back to text: {e}")
                            await self._send_text_response(
                                message.channel, response_text
                            )
                    else:
                        await self._send_text_response(message.channel, response_text)
                else:
                    await self._send_text_response(message.channel, response_text)

                # Extract and create memos
                if self._task_scheduler:
                    memos = self._extract_memos(response_text)
                    for memo in memos:
                        await self._create_memo_from_tag(user_id, memo)

                # Send files
                files_to_send = self._extract_file_paths(response_text)
                for file_path in files_to_send:
                    await self.send_file(message.channel, file_path)

            except Exception as e:
                await thinking_msg.delete()
                logger.exception(f"Error processing voice message: {e}")
                await message.channel.send(_("Error: {error}").format(error=str(e)))

        finally:
            voice_path.unlink(missing_ok=True)

    async def _send_text_response(
        self, channel: discord.TextChannel, response_text: str
    ) -> None:
        """Send text response, handling formatting and chunking."""
        response_text = self._remove_file_tags(response_text)

        if response_text.strip():
            formatted_text = self._convert_tables_to_code_blocks(response_text)
            chunks = self._split_message(formatted_text, DISCORD_MAX_MESSAGE_LENGTH)
            for chunk in chunks:
                await channel.send(chunk)

    # --- Attachment handling ---

    async def _handle_attachment(self, message: discord.Message, caption: str) -> None:
        user_id = message.author.id
        username = message.author.name
        self._set_user_language(username)

        # Reject if already processing
        if user_id in self._active_tasks and not self._active_tasks[user_id].done():
            await message.channel.send(
                _("A request is already running. Use !stop to cancel it.")
            )
            return

        sessions_service = (
            self._plugin_manager.get_service("sessions")
            if self._plugin_manager
            else None
        )
        attachments_service = (
            self._plugin_manager.get_service("attachments")
            if self._plugin_manager
            else None
        )

        if not sessions_service or not attachments_service:
            await message.channel.send(_("Services not available."))
            return

        session = await sessions_service.get_session(user_id, "discord")
        if not session:
            session = await sessions_service.create_session(user_id, "discord")

        attachment_paths = []
        for attachment in message.attachments:
            path = await attachments_service.download_discord(attachment, session.id)
            attachment_paths.append(str(path))

        if attachment_paths and self._message_handler:
            text = caption if caption else _("[Attachments received]")
            is_dm = isinstance(message.channel, discord.DMChannel)
            msg = Message(
                user_id=user_id,
                username=username,
                text=text,
                attachments=attachment_paths,
                platform="discord",
                is_group_chat=not is_dm,
            )
            user_info = UserInfo(
                user_id=user_id,
                username=username,
                display_name=message.author.display_name,
                platform="discord",
            )

            # Store user message in chat history
            await sessions_service.store_chat_message(
                user_id=user_id,
                platform="discord",
                role="user",
                content=text,
                username=username,
            )

            thinking_msg = await message.channel.send(_("Thinking..."))
            progress_cb, error_cb, tool_cb, stream_cb = self._create_runner_callbacks(
                thinking_msg
            )

            async with message.channel.typing():
                try:
                    response_text = await self._message_handler(
                        msg,
                        user_info,
                        progress_callback=progress_cb,
                        error_callback=error_cb,
                        tool_callback=tool_cb,
                        stream_callback=stream_cb,
                    )
                    await thinking_msg.delete()

                    # Memo extraction
                    if self._task_scheduler:
                        memos = self._extract_memos(response_text)
                        for memo in memos:
                            await self._create_memo_from_tag(user_id, memo)
                        response_text = self._remove_memo_tags(response_text)

                    # File extraction
                    files_to_send = self._extract_file_paths(response_text)
                    response_text = self._remove_file_tags(response_text)

                    # Store assistant response in chat history
                    if response_text.strip():
                        await sessions_service.store_chat_message(
                            user_id=user_id,
                            platform="discord",
                            role="assistant",
                            content=response_text,
                            username=username,
                        )

                        formatted_text = self._convert_tables_to_code_blocks(
                            response_text
                        )
                        chunks = self._split_message(
                            formatted_text, DISCORD_MAX_MESSAGE_LENGTH
                        )
                        for chunk in chunks:
                            await message.channel.send(chunk)

                    # Send extracted files
                    for file_path in files_to_send:
                        await self.send_file(message.channel, file_path)

                except Exception as e:
                    await thinking_msg.delete()
                    logger.exception(f"Error processing attachment: {e}")
                    await message.channel.send(_("Error: {error}").format(error=str(e)))

    # --- Main message processing ---

    async def _process_request(self, ctx: commands.Context, content: str) -> None:
        """Process a user request."""
        user_id = ctx.author.id
        username = ctx.author.name
        self._set_user_language(username)

        if not self._message_handler:
            await ctx.send(_("Handler not configured."))
            return

        is_dm = isinstance(ctx.channel, discord.DMChannel)
        message = Message(
            user_id=user_id,
            username=username,
            text=content,
            platform="discord",
            is_group_chat=not is_dm,
        )
        user_info = UserInfo(
            user_id=user_id,
            username=username,
            display_name=ctx.author.display_name,
            platform="discord",
        )

        # Store user message in chat history
        sessions_service = (
            self._plugin_manager.get_service("sessions")
            if self._plugin_manager
            else None
        )
        if sessions_service:
            await sessions_service.store_chat_message(
                user_id=user_id,
                platform="discord",
                role="user",
                content=content,
                username=username,
            )

        # Reject if already processing
        if user_id in self._active_tasks and not self._active_tasks[user_id].done():
            await ctx.send(_("A request is already running. Use !stop to cancel it."))
            return

        thinking_msg = await ctx.send(_("Thinking..."))
        task = asyncio.create_task(
            self._run_message_pipeline(ctx, message, user_info, thinking_msg)
        )
        self._active_tasks[user_id] = task

        try:
            await task
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await thinking_msg.delete()
            await ctx.send(_("Request cancelled."))
        finally:
            self._active_tasks.pop(user_id, None)

    async def _run_message_pipeline(
        self,
        ctx: commands.Context,
        message: Message,
        user_info: UserInfo,
        thinking_msg,
    ) -> None:
        """Execute the full message processing pipeline (runs as tracked task)."""
        progress_cb, error_cb, tool_cb, stream_cb = self._create_runner_callbacks(
            thinking_msg
        )

        async with ctx.typing():
            try:
                response_text = await self._message_handler(
                    message,
                    user_info,
                    progress_callback=progress_cb,
                    error_callback=error_cb,
                    tool_callback=tool_cb,
                    stream_callback=stream_cb,
                )
                await thinking_msg.delete()

                # Extract and create memos
                if self._task_scheduler:
                    memos = self._extract_memos(response_text)
                    for memo in memos:
                        await self._create_memo_from_tag(message.user_id, memo)
                    response_text = self._remove_memo_tags(response_text)

                # Extract and process history search requests
                sessions_service = (
                    self._plugin_manager.get_service("sessions")
                    if self._plugin_manager
                    else None
                )
                # Extract files
                files_to_send = self._extract_file_paths(response_text)
                response_text = self._remove_file_tags(response_text)

                # Store assistant response in chat history
                if sessions_service and response_text.strip():
                    await sessions_service.store_chat_message(
                        user_id=message.user_id,
                        platform="discord",
                        role="assistant",
                        content=response_text,
                        username=message.username,
                    )

                if response_text.strip():
                    formatted_text = self._convert_tables_to_code_blocks(response_text)
                    chunks = self._split_message(
                        formatted_text, DISCORD_MAX_MESSAGE_LENGTH
                    )
                    for chunk in chunks:
                        await ctx.send(chunk)

                # Send files
                for file_path in files_to_send:
                    await self.send_file(ctx.channel, file_path)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                with contextlib.suppress(Exception):
                    await thinking_msg.delete()
                logger.exception(f"Error processing message: {e}")
                await ctx.send(_("Error: {error}").format(error=str(e)))

    # --- Static utilities ---

    @staticmethod
    def _convert_tables_to_code_blocks(text: str) -> str:
        """Convert markdown tables to code blocks for better rendering."""
        table_pattern = re.compile(r"((?:^\|.+\|$\n?)+)", re.MULTILINE)

        def replace_table(match):
            table = match.group(1).strip()
            if "|---" in table or "| ---" in table or "|:--" in table:
                return f"```\n{table}\n```"
            return table

        return table_pattern.sub(replace_table, text)

    @staticmethod
    def _split_message(text: str, max_length: int) -> list[str]:
        """Split long message into chunks."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            split_pos = text.rfind("\n", 0, max_length)
            if split_pos == -1:
                split_pos = text.rfind(" ", 0, max_length)
            if split_pos == -1:
                split_pos = max_length

            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip()

        return chunks

    @staticmethod
    def _extract_memos(text: str) -> List[dict]:
        """Extract [CREATE_MEMO: type | schedule | title | task] tags."""
        memos = []
        # Try 4-part format: type | schedule | title | task
        pattern_4 = (
            r"\[CREATE_MEMO:\s*([^|]+)\s*\|\s*([^|]+)\s*\|"
            r"\s*([^|]+)\s*\|\s*([^\]]+)\]"
        )
        matches = re.findall(pattern_4, text, re.IGNORECASE)
        for match in matches:
            memos.append(
                {
                    "type": match[0].strip().lower(),
                    "schedule": match[1].strip(),
                    "title": match[2].strip(),
                    "task": match[3].strip(),
                }
            )

        # Fallback to 3-part format: type | schedule | task
        if not memos:
            pattern_3 = (
                r"\[CREATE_MEMO:\s*([^|]+)\s*\|\s*([^|]+)\s*\|"
                r"\s*([^\]]+)\]"
            )
            matches = re.findall(pattern_3, text, re.IGNORECASE)
            for match in matches:
                task = match[2].strip()
                memos.append(
                    {
                        "type": match[0].strip().lower(),
                        "schedule": match[1].strip(),
                        "title": task[:50],
                        "task": task,
                    }
                )
        return memos

    @staticmethod
    def _remove_memo_tags(text: str) -> str:
        """Remove [CREATE_MEMO: ...] tags from text."""
        return re.sub(r"\[CREATE_MEMO:[^\]]+\]", "", text, flags=re.IGNORECASE).strip()

    @staticmethod
    def _extract_file_paths(text: str) -> List[str]:
        """Extract file paths from [SEND_FILE: path] tags (deprecated fallback)."""
        matches = re.findall(r"\[SEND_FILE:\s*(.+?)\]", text, re.IGNORECASE)
        if matches:
            logger.warning(
                "DEPRECATED: [SEND_FILE:] tag used — migrate to send_file_to_chat MCP tool"
            )
        resolved = []
        for m in matches:
            path = m.strip()
            p = Path(path)
            if not p.is_absolute() and not p.exists():
                for search_dir in ["/app/data/playwright", "/app/data"]:
                    candidate = Path(search_dir) / p
                    if candidate.exists():
                        path = str(candidate)
                        logger.info(f"Resolved relative path '{m.strip()}' → '{path}'")
                        break
            resolved.append(path)
        return resolved

    @staticmethod
    def _remove_file_tags(text: str) -> str:
        """Remove [SEND_FILE: ...] tags from text."""
        return re.sub(r"\[SEND_FILE:\s*.+?\]", "", text, flags=re.IGNORECASE).strip()

    async def send_file(
        self,
        user_id: int | str,
        file_path: str,
        caption: str | None = None,
    ) -> bool:
        """Send a file to a channel.

        Args:
            user_id: Discord channel ID (int or str) or a discord.TextChannel object
                     (for backward compatibility with tag-based flow).
            file_path: Absolute path to the file
            caption: Optional caption/message
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return False

        # Resolve channel: accept both ID and discord.TextChannel object
        if isinstance(user_id, (int, str)) and not hasattr(user_id, "send"):
            channel = self.bot.get_channel(int(user_id))
            if not channel:
                logger.error(f"Discord channel {user_id} not found")
                return False
        else:
            channel = user_id

        try:
            await channel.send(
                content=caption or None,
                file=discord.File(str(path)),
            )
            logger.info(f"Sent file {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to send file {file_path}: {e}")
            return False

    async def _create_memo_from_tag(self, user_id: int, memo: dict) -> int | None:
        """Create a memo/scheduled task from parsed tag."""
        if not self._task_scheduler:
            return None

        try:
            memo_type = memo.get("type", "once")
            schedule = memo.get("schedule", "")
            title = memo.get("title", "")
            task = memo.get("task", "")

            if memo_type == "cron":
                memo_id = await self._task_scheduler.add_memo(
                    user_id=user_id,
                    platform="discord",
                    schedule_type="cron",
                    prompt=task,
                    description=title,
                    cron=schedule,
                )
                logger.info(
                    f"Created recurring memo {memo_id} for user {user_id}: "
                    f"{title} ({schedule})"
                )
                return memo_id
            else:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                run_at = datetime.fromisoformat(schedule)
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=ZoneInfo("Europe/Rome"))

                memo_id = await self._task_scheduler.add_memo(
                    user_id=user_id,
                    platform="discord",
                    schedule_type="once",
                    prompt=task,
                    description=title,
                    run_at=run_at,
                )
                logger.info(
                    f"Created one-time memo {memo_id} for user {user_id}: "
                    f"{title} ({run_at})"
                )
                return memo_id

        except Exception as e:
            logger.error(f"Failed to create memo from tag: {e}")

    # --- Scheduled tasks ---

    async def execute_scheduled_task(self, user_id: int, prompt: str) -> None:
        """Execute a scheduled task and send result to user."""
        channel_id = self._user_channels.get(user_id)
        if not channel_id or not self._message_handler:
            logger.warning(f"Cannot execute scheduled task for user {user_id}")
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            logger.warning(f"Channel {channel_id} not found for scheduled task")
            return

        username = self._user_usernames.get(user_id)
        message = Message(
            user_id=user_id,
            username=username,
            text=prompt,
            platform="discord",
        )
        user_info = UserInfo(
            user_id=user_id,
            username=username,
            display_name="Scheduled",
            platform="discord",
        )

        try:
            response_text = await self._message_handler(message, user_info)

            # Extract and create follow-up memos
            if self._task_scheduler:
                memos = self._extract_memos(response_text)
                for memo in memos:
                    await self._create_memo_from_tag(user_id, memo)
                response_text = self._remove_memo_tags(response_text)

            # Extract files
            files_to_send = self._extract_file_paths(response_text)
            response_text = self._remove_file_tags(response_text)

            formatted_text = f"**Memo**\n\n{response_text}"
            formatted_text = self._convert_tables_to_code_blocks(formatted_text)
            chunks = self._split_message(formatted_text, DISCORD_MAX_MESSAGE_LENGTH)

            for chunk in chunks:
                await channel.send(chunk)

            # Send files
            for file_path in files_to_send:
                await self.send_file(channel, file_path)

        except Exception as e:
            logger.exception(f"Error executing scheduled task: {e}")
