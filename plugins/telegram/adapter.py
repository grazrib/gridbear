"""Telegram Channel Plugin.

Telegram bot adapter implementing BaseChannel interface.
"""

import asyncio
import contextlib
import re
import uuid
from pathlib import Path
from typing import List

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config.logging_config import logger
from config.settings import (
    get_unified_user_id,
    get_user_locale,
)
from core.i18n import make_translator, set_language
from core.interfaces.channel import BaseChannel, Message, UserInfo
from sessions.context_builder import UserInfo as ContextUserInfo
from ui.secrets_manager import secrets_manager

# Create translator for this plugin
_ = make_translator("telegram")

TELEGRAM_MAX_MESSAGE_LENGTH = 4000

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

        # Build time string
        time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"

        # Determine frequency
        if day == "*" and month == "*" and dow == "*":
            if locale == "it":
                return f"Ogni giorno alle {time_str}"
            return f"Every day at {time_str}"
        elif dow != "*" and day == "*":
            # Specific day(s) of week
            day_name = DAYS_OF_WEEK.get(dow.lower(), dow)
            if locale == "it":
                day_name = DAYS_IT.get(day_name, day_name)
                return f"Ogni {day_name} alle {time_str}"
            return f"Every {day_name} at {time_str}"
        elif day != "*" and month == "*":
            # Specific day of month
            if locale == "it":
                return f"Il giorno {day} di ogni mese alle {time_str}"
            return f"Day {day} of every month at {time_str}"
        else:
            # Complex expression, return simplified
            if locale == "it":
                return f"Ricorrente alle {time_str}"
            return f"Recurring at {time_str}"
    except Exception:
        return cron


class TelegramChannel(BaseChannel):
    """Telegram messaging channel."""

    platform = "telegram"

    def __init__(self, config: dict):
        super().__init__(config)
        token_env = config.get("token_env", "TELEGRAM_BOT_TOKEN")
        self.token = secrets_manager.get_plain(token_env)
        self.app: Application | None = None
        self._bot_username: str | None = None
        self._user_usernames: dict[int, str] = {}
        self._active_tasks: dict[int, asyncio.Task] = {}

    def _create_runner_callbacks(self, thinking_msg):
        """Create progress, error, and tool callbacks for runner.

        Args:
            thinking_msg: The telegram message to update with progress

        Returns:
            Tuple of (progress_callback, error_callback, tool_callback)
        """

        async def progress_callback(progress_message: str):
            """Update thinking message with progress."""
            try:
                await thinking_msg.edit_text(progress_message)
            except Exception as e:
                logger.warning(f"Failed to update progress message: {e}")

        async def error_callback(error_type: str, details: dict):
            """Handle runner errors with user notification."""
            logger.error(f"Runner error [{error_type}]: {details}")
            try:
                if error_type == "timeout":
                    timeout_secs = details.get("timeout_seconds", "?")
                    await thinking_msg.edit_text(
                        f"Timeout dopo {timeout_secs} secondi. "
                        "La richiesta era troppo complessa. Riprova semplificando."
                    )
                elif error_type == "exception":
                    error_msg = details.get("error", "Errore sconosciuto")
                    await thinking_msg.edit_text(
                        f"Si è verificato un errore: {error_msg[:100]}"
                    )
                elif error_type == "retries_exhausted":
                    await thinking_msg.edit_text(
                        "Tutti i tentativi falliti. Riprova più tardi."
                    )
            except Exception as e:
                logger.warning(f"Failed to send error notification: {e}")

        async def tool_callback(tool_name: str, tool_input: dict):
            """Notify user about tool being used."""
            try:
                if tool_input.get("_grouped"):
                    # Pre-formatted grouped notification
                    status_text = tool_name
                else:
                    from core.tool_display import format_tool_status

                    status_text = format_tool_status(tool_name, tool_input)
                await thinking_msg.edit_text(status_text)
            except Exception as e:
                logger.debug(f"Failed to update tool status: {e}")

        return progress_callback, error_callback, tool_callback

    def _set_user_language(self, username: str | None) -> None:
        """Set translation language based on user's locale preference."""
        if username:
            unified_id = get_unified_user_id("telegram", username)
            locale = get_user_locale(unified_id)
            set_language(locale)
        else:
            set_language("en")

    async def initialize(self) -> None:
        """Initialize Telegram bot."""
        if not self.token:
            logger.warning("Telegram token not configured")
            return
        logger.info("Telegram channel initialized")

    async def start(self) -> None:
        """Build and start Telegram bot."""
        if not self.token:
            logger.warning("Cannot start Telegram: no token configured")
            return

        self.app = Application.builder().token(self.token).build()

        # Get bot username for mention detection in groups
        bot_info = await self.app.bot.get_me()
        self._bot_username = bot_info.username
        logger.debug(f"Bot username: @{self._bot_username}")

        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("reset", self._cmd_reset))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("memo", self._cmd_tasks))
        self.app.add_handler(CommandHandler("delmemo", self._cmd_deltask))
        self.app.add_handler(CommandHandler("memory", self._cmd_memory))
        self.app.add_handler(CommandHandler("stop", self._cmd_stop))
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )
        self.app.add_handler(
            MessageHandler(filters.VOICE & ~filters.COMMAND, self._handle_voice)
        )
        self.app.add_handler(
            MessageHandler(
                filters.ATTACHMENT & ~filters.VOICE & ~filters.COMMAND,
                self._handle_attachment,
            )
        )

        logger.info("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        """Stop Telegram bot."""
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
            logger.info("Telegram bot stopped")

    async def send_message(
        self,
        user_id: int,
        text: str,
        attachments: list[str] | None = None,
    ) -> None:
        """Send message to a user."""
        if not self.app:
            return

        formatted_text = self._convert_tables_to_code_blocks(text)
        chunks = self._split_message(formatted_text, TELEGRAM_MAX_MESSAGE_LENGTH)

        for chunk in chunks:
            try:
                await self.app.bot.send_message(
                    chat_id=user_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.info(f"Markdown failed, sending plain: {e}")
                await self.app.bot.send_message(chat_id=user_id, text=chunk)

        if attachments:
            for attachment_path in attachments:
                path = Path(attachment_path)
                if path.exists():
                    with open(path, "rb") as f:
                        await self.app.bot.send_document(chat_id=user_id, document=f)

    async def get_user_info(self, user_id: int) -> UserInfo | None:
        """Get user information."""
        username = self._user_usernames.get(user_id)
        return UserInfo(
            user_id=user_id,
            username=username,
            display_name=username,
            platform="telegram",
        )

    def _cache_username(self, user_id: int, username: str | None):
        """Cache username for scheduled tasks."""
        if username:
            self._user_usernames[user_id] = username.lower()

    def _get_unified_id(self, username: str | None) -> str | None:
        """Get unified ID for username."""
        if not username:
            return None
        return get_unified_user_id("telegram", username)

    def _get_context_user_info(self, update: Update) -> ContextUserInfo:
        """Extract user info from Telegram update."""
        user = update.effective_user
        return ContextUserInfo(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            platform="telegram",
        )

    async def _cmd_start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)
        await update.message.reply_text(
            _(
                "Hello! I'm your GridBear assistant.\n"
                "Write anything and I'll respond.\n"
                "Use /reset to start a new conversation."
            )
        )

    async def _cmd_reset(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
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
            session_ids = await sessions_service.clear_session(user_id, "telegram")
            if attachments_service:
                for sid in session_ids:
                    await attachments_service.cleanup_session(sid)

        await update.message.reply_text(_("Session reset. Start a new chat!"))

    async def _cmd_help(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        username = update.effective_user.username
        self._set_user_language(username)

        await update.message.reply_text(
            _(
                "*GridBear Commands*\n\n"
                "*Chat:*\n"
                "/start - Welcome message\n"
                "/reset - Reset session\n"
                "/help - Show this message\n"
                "/stop - Stop current request\n\n"
                "*Memory:*\n"
                "/memory - Memory management\n\n"
                "*Memos/Reminders:*\n"
                "/memo - List memos\n"
                "/delmemo <id> - Delete memo\n"
                "/delmemo all - Delete all\n\n"
                "*Creating memos:*\n"
                '"gridbear remind me every Monday at 9 to X"\n'
                '"gridbear in 30 minutes tell me Y"\n\n'
                "You can also send attachments (documents, images)."
            ),
            parse_mode="Markdown",
        )

    async def _cmd_tasks(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)
        logger.debug(f"/memo command from user {user_id} ({username})")

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        if not self._task_scheduler:
            logger.warning(f"/memo: memo_service is None for user {user_id}")
            await update.message.reply_text(_("Memo service not available."))
            return

        logger.debug(f"/memo: calling list_memos for user {user_id}")
        tasks = await self._task_scheduler.list_memos(user_id, "telegram")
        logger.debug(f"/memo: got {len(tasks)} memos for user {user_id}")
        if not tasks:
            await update.message.reply_text(_("No memos."))
            return

        # Get user locale for human-readable schedule
        unified_id = get_unified_user_id("telegram", username) if username else None
        locale = get_user_locale(unified_id) if unified_id else "en"

        lines = [_("*Your memos:*\n")]
        for t in tasks:
            status = "✅" if t["enabled"] else "⏸️"

            # Get human-readable schedule
            if t.get("schedule_type") == "cron" and t.get("cron"):
                when = cron_to_human(t["cron"], locale)
            elif t.get("run_at"):
                # One-time memo - show date/time
                try:
                    from datetime import datetime

                    run_at = datetime.fromisoformat(t["run_at"])
                    when = run_at.strftime("%d/%m/%Y %H:%M")
                except Exception:
                    when = t["run_at"]
            else:
                when = t.get("description", "")

            # Get memo description - use title if available, otherwise truncated content
            title = t.get("prompt_title", "")
            content = t.get("prompt_content", "") or t.get("prompt", "")
            display_text = (
                title
                if title
                else (content[:80] + "..." if len(content) > 80 else content)
            )
            # Escape markdown special chars
            display_text = (
                display_text.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")
            )
            when = when.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`")

            lines.append(f"{status} *{t['id']}*: {display_text}")
            lines.append(f"   ⏰ {when}")
            if t.get("last_run"):
                lines.append(f"   {_('Last run:')} {t['last_run'][:16]}")
        try:
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        except Exception:
            # Fallback to plain text if markdown fails
            await update.message.reply_text(
                "\n".join(lines).replace("*", "").replace("\\", "")
            )

    async def _cmd_deltask(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        if not self._task_scheduler:
            await update.message.reply_text(_("Memo service not available."))
            return

        args = context.args
        if not args:
            await update.message.reply_text(_("Usage: /delmemo <id> or /delmemo all"))
            return

        if args[0].lower() == "all":
            memos = await self._task_scheduler.list_memos(user_id, "telegram")
            count = 0
            for m in memos:
                if await self._task_scheduler.delete_memo(m["id"], user_id):
                    count += 1
            await update.message.reply_text(
                _("Deleted {count} memo(s).").format(count=count)
            )
        else:
            try:
                memo_id = int(args[0])
                if await self._task_scheduler.delete_memo(memo_id, user_id):
                    await update.message.reply_text(
                        _("Memo {memo_id} deleted.").format(memo_id=memo_id)
                    )
                else:
                    await update.message.reply_text(_("Memo not found."))
            except ValueError:
                await update.message.reply_text(_("Invalid ID."))

    async def _cmd_memory(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Memory management command."""
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)
        unified_id = get_unified_user_id("telegram", username) if username else None

        memory_service = (
            self._plugin_manager.get_service("memory") if self._plugin_manager else None
        )
        if not memory_service or not memory_service.enabled:
            await update.message.reply_text(_("Memory service not available."))
            return

        args = context.args
        if not args:
            await self._memory_help(update)
            return

        subcommand = args[0].lower()

        if subcommand == "help":
            await self._memory_help(update)
        elif subcommand == "stats":
            await self._memory_stats(update, memory_service, username)
        elif subcommand == "list":
            limit = int(args[1]) if len(args) > 1 and args[1].isdigit() else 5
            await self._memory_list(update, memory_service, username, limit)
        elif subcommand == "search":
            if len(args) < 2:
                await update.message.reply_text(_("Usage: /memory search <query>"))
                return
            query = " ".join(args[1:])
            await self._memory_search(update, memory_service, unified_id, query)
        elif subcommand == "delete":
            if len(args) < 2:
                await update.message.reply_text(_("Usage: /memory delete <id>"))
                return
            await self._memory_delete(update, memory_service, args[1])
        elif subcommand == "clear":
            if len(args) < 2:
                await update.message.reply_text(
                    _(
                        "*Usage:* /memory clear <type>\n\n"
                        "*Types:* `all`, `episodic`, `facts`"
                    ),
                    parse_mode="Markdown",
                )
                return
            await self._memory_clear(update, memory_service, username, args[1])
        else:
            await self._memory_help(update)

    async def _memory_help(self, update: Update) -> None:
        """Show memory command help."""
        await update.message.reply_text(
            _(
                "*Memory Management*\n\n"
                "*Commands:*\n"
                "`/memory stats` - Your memory statistics\n"
                "`/memory list [n]` - List last n memories (default 5)\n"
                "`/memory search <query>` - Semantic search\n"
                "`/memory delete <id>` - Delete a memory\n"
                "`/memory clear <type>` - Clear your memories\n\n"
                "*Clear types:* `all`, `episodic`, `facts`"
            ),
            parse_mode="Markdown",
        )

    async def _memory_stats(
        self, update: Update, memory_service, username: str
    ) -> None:
        """Show memory statistics for user."""
        stats = memory_service.get_memory_stats("telegram", username)
        await update.message.reply_text(
            _(
                "*Your Memory Stats*\n\n"
                "Episodic: {episodic}\n"
                "Declarative: {declarative}\n"
                "Total: {total}"
            ).format(**stats),
            parse_mode="Markdown",
        )

    async def _memory_list(
        self, update: Update, memory_service, username: str, limit: int
    ) -> None:
        """List recent memories for user."""
        memories = memory_service.get_all_memories("telegram", username)
        memories = memories[:limit]

        if not memories:
            await update.message.reply_text(_("No memories found."))
            return

        lines = [_("*Your Recent Memories*\n")]
        for mem in memories:
            mem_type = "E" if mem.get("memory_type") == "episodic" else "D"
            content = mem.get("content", "")[:80]
            if len(mem.get("content", "")) > 80:
                content += "..."
            mem_id = mem.get("id", "")[:8]
            lines.append(f"`[{mem_type}] {mem_id}` {content}\n")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _memory_search(
        self, update: Update, memory_service, unified_id: str, query: str
    ) -> None:
        """Search memories semantically."""
        results = await memory_service.get_relevant(query, unified_id, limit=5)

        if not results:
            await update.message.reply_text(_("No matching memories found."))
            return

        lines = [_("*Search Results*\n")]
        for mem in results:
            mem_type = "E" if mem.get("memory_type") == "episodic" else "D"
            content = mem.get("content", "")[:80]
            if len(mem.get("content", "")) > 80:
                content += "..."
            relevance = int(mem.get("relevance", 0) * 100)
            lines.append(f"`[{mem_type}] {relevance}%` {content}\n")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _memory_delete(
        self, update: Update, memory_service, memory_id: str
    ) -> None:
        """Delete a specific memory."""
        deleted = await memory_service.delete_memory(memory_id)
        if deleted:
            await update.message.reply_text(
                _("Memory {id} deleted.").format(id=memory_id[:8])
            )
        else:
            await update.message.reply_text(_("Memory not found."))

    async def _memory_clear(
        self,
        update: Update,
        memory_service,
        username: str,
        mode: str,
    ) -> None:
        """Clear user's own memories by mode."""
        mode = mode.lower()
        type_map = {"all": None, "episodic": "episodic", "facts": "declarative"}
        if mode not in type_map:
            await update.message.reply_text(
                _("Invalid type. Use: all, episodic, facts")
            )
            return
        try:
            memory_service.clear_user_memories(
                "telegram",
                username,
                memory_type=type_map[mode],
            )
            await update.message.reply_text(
                _("Memories cleared (type: {mode}).").format(mode=mode)
            )
        except Exception as e:
            logger.exception(f"Error clearing memory: {e}")
            await update.message.reply_text(f"Error: {e}")

    async def _handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        text_override: str | None = None,
    ) -> None:
        user_id = update.effective_user.id
        text = text_override or update.message.text
        if not text:
            return

        is_private = update.effective_chat.type == "private"
        # In groups, respond only if bot is mentioned (@username)
        is_mentioned = (
            self._bot_username and f"@{self._bot_username}".lower() in text.lower()
        )

        if not is_private and not is_mentioned:
            return

        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        # Message is processed by Claude, which can create memos using [CREATE_MEMO: ...] tags
        if self._message_handler:
            message = Message(
                user_id=user_id,
                username=username,
                text=text,
                platform="telegram",
                is_group_chat=not is_private,
            )
            user_info = UserInfo(
                user_id=user_id,
                username=username,
                display_name=update.effective_user.first_name,
                platform="telegram",
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
                    platform="telegram",
                    role="user",
                    content=text,
                    username=username,
                )

            # Reject if already processing
            if user_id in self._active_tasks and not self._active_tasks[user_id].done():
                await update.message.reply_text(
                    _("A request is already running. Use /stop to cancel it.")
                )
                return

            thinking_msg = await update.message.reply_text(_("Thinking..."))
            task = asyncio.create_task(
                self._run_message_pipeline(update, message, user_info, thinking_msg)
            )
            self._active_tasks[user_id] = task

            try:
                await task
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await thinking_msg.delete()
                await update.message.reply_text(_("Request cancelled."))
            finally:
                self._active_tasks.pop(user_id, None)

    async def _run_message_pipeline(
        self,
        update: Update,
        message: Message,
        user_info: UserInfo,
        thinking_msg,
    ) -> None:
        """Execute the full message processing pipeline (runs as tracked task)."""
        progress_cb, error_cb, tool_cb = self._create_runner_callbacks(thinking_msg)

        try:
            response_text = await self._message_handler(
                message,
                user_info,
                progress_callback=progress_cb,
                error_callback=error_cb,
                tool_callback=tool_cb,
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
            # Extract and send files
            files_to_send = self._extract_file_paths(response_text)
            response_text = self._remove_file_tags(response_text)

            # Store assistant response in chat history
            if sessions_service and response_text.strip():
                await sessions_service.store_chat_message(
                    user_id=message.user_id,
                    platform="telegram",
                    role="assistant",
                    content=response_text,
                    username=message.username,
                )

            if response_text.strip():
                formatted_text = self._convert_tables_to_code_blocks(response_text)
                chunks = self._split_message(
                    formatted_text, TELEGRAM_MAX_MESSAGE_LENGTH
                )
                for chunk in chunks:
                    await self._send_markdown(update, chunk)

            # Send files as photos or documents (to the chat, not user's private)
            chat_id = update.effective_chat.id
            for file_path in files_to_send:
                await self.send_file(chat_id, file_path)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            with contextlib.suppress(Exception):
                await thinking_msg.delete()
            logger.exception(f"Error processing message: {e}")
            await update.message.reply_text(_("Error: {error}").format(error=str(e)))

    async def _cmd_stop(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /stop command — cancel the active request for this user."""
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        task = self._active_tasks.get(user_id)
        if not task or task.done():
            await update.message.reply_text(_("No active request to stop."))
            return

        task.cancel()

        # Also cancel any async background tasks for this agent
        from core.mcp_gateway.server import get_task_manager

        task_manager = get_task_manager()
        if task_manager and self.agent_name:
            cancelled = task_manager.cancel_tasks_by_agent(self.agent_name)
            if cancelled:
                logger.info(
                    "Cancelled %d async tasks for agent %s", cancelled, self.agent_name
                )

        await update.message.reply_text(_("Stopping..."))

    async def _handle_voice(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle voice messages: transcribe, process, and respond with voice."""
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        # Reject if already processing
        if user_id in self._active_tasks and not self._active_tasks[user_id].done():
            await update.message.reply_text(
                _("A request is already running. Use /stop to cancel it.")
            )
            return

        voice = update.message.voice
        if not voice:
            return

        file = await voice.get_file()
        voice_path = Path(f"/tmp/gridbear_voice_{uuid.uuid4().hex}.ogg")

        try:
            await file.download_to_drive(voice_path)

            voice_service = (
                self._plugin_manager.get_service("transcription")
                if self._plugin_manager
                else None
            )
            if not voice_service:
                await update.message.reply_text(_("Voice service not available."))
                return

            transcribing_msg = await update.message.reply_text(_("Transcribing..."))
            text = await voice_service.transcribe(str(voice_path))
            await transcribing_msg.delete()

            if not text:
                await update.message.reply_text(
                    _("Could not transcribe voice message.")
                )
                return

            await update.message.reply_text(f"_{text}_", parse_mode="Markdown")

            is_private = update.effective_chat.type == "private"
            # In groups, respond only if bot is mentioned (@username)
            is_mentioned = (
                self._bot_username and f"@{self._bot_username}".lower() in text.lower()
            )

            if not is_private and not is_mentioned:
                return

            # Process with Claude
            if not self._message_handler:
                return

            message = Message(
                user_id=user_id,
                username=username,
                text=text,
                platform="telegram",
                respond_with_voice=True,
                is_group_chat=not is_private,
            )
            user_info = UserInfo(
                user_id=user_id,
                username=username,
                display_name=update.effective_user.first_name,
                platform="telegram",
            )

            thinking_msg = await update.message.reply_text(_("Thinking..."))
            progress_cb, error_cb, tool_cb = self._create_runner_callbacks(thinking_msg)

            try:
                response_text = await self._message_handler(
                    message,
                    user_info,
                    progress_callback=progress_cb,
                    error_callback=error_cb,
                    tool_callback=tool_cb,
                )
                await thinking_msg.delete()

                # Try to respond with voice (per-agent TTS service)
                tts_service = None
                if self._agent:
                    try:
                        tts_service = self._agent.get_service("tts")
                    except Exception:
                        pass
                if tts_service and response_text.strip():
                    # Get voice config: agent-specific or user locale-based
                    agent_ctx = self.get_agent_context()
                    voice_config = agent_ctx.get("voice", {})
                    voice_id = voice_config.get("voice_id")

                    # Fallback to user's locale for voice selection
                    unified_id = (
                        get_unified_user_id("telegram", username) if username else None
                    )
                    locale = get_user_locale(unified_id) if unified_id else "en"

                    # Clean text for TTS: remove tags and markdown
                    clean_text = response_text
                    clean_text = self._remove_file_tags(clean_text)
                    clean_text = self._strip_markdown_for_tts(clean_text)

                    if clean_text.strip():
                        try:
                            # Use agent voice if available, otherwise locale-based
                            if voice_id:
                                audio_path = await tts_service.synthesize(
                                    clean_text.strip(), voice=voice_id
                                )
                            else:
                                audio_path = await tts_service.synthesize(
                                    clean_text.strip(), locale=locale
                                )
                            with open(audio_path, "rb") as audio_file:
                                await update.message.reply_voice(voice=audio_file)
                            Path(audio_path).unlink(missing_ok=True)
                        except Exception as e:
                            logger.warning(f"TTS failed, falling back to text: {e}")
                            await self._send_text_response(update, response_text)
                    else:
                        await self._send_text_response(update, response_text)
                else:
                    await self._send_text_response(update, response_text)

                # Extract and create memos
                if self._task_scheduler:
                    memos = self._extract_memos(response_text)
                    for memo in memos:
                        await self._create_memo_from_tag(user_id, memo)
                    response_text = self._remove_memo_tags(response_text)

                # Send any files
                files_to_send = self._extract_file_paths(response_text)
                chat_id = update.effective_chat.id
                for file_path in files_to_send:
                    await self.send_file(chat_id, file_path)

            except Exception as e:
                await thinking_msg.delete()
                logger.exception(f"Error processing voice message: {e}")
                await update.message.reply_text(
                    _("Error: {error}").format(error=str(e))
                )

        finally:
            voice_path.unlink(missing_ok=True)

    async def _send_text_response(self, update: Update, response_text: str) -> None:
        """Send text response, handling formatting and chunking."""
        response_text = self._remove_file_tags(response_text)

        if response_text.strip():
            formatted_text = self._convert_tables_to_code_blocks(response_text)
            chunks = self._split_message(formatted_text, TELEGRAM_MAX_MESSAGE_LENGTH)
            for chunk in chunks:
                await self._send_markdown(update, chunk)

    async def _handle_attachment(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        logger.debug(
            f"_handle_attachment called: document={update.message.document}, photo={update.message.photo}, audio={update.message.audio}"
        )
        user_id = update.effective_user.id
        username = update.effective_user.username
        self._set_user_language(username)

        if not self.is_authorized(user_id, username):
            await update.message.reply_text(_("Not authorized."))
            return

        self._cache_username(user_id, username)

        # Reject if already processing
        if user_id in self._active_tasks and not self._active_tasks[user_id].done():
            await update.message.reply_text(
                _("A request is already running. Use /stop to cancel it.")
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
            await update.message.reply_text(_("Services not available."))
            return

        session = await sessions_service.get_session(user_id, "telegram")
        if not session:
            session = await sessions_service.create_session(user_id, "telegram")

        caption = update.message.caption or ""
        document = update.message.document
        photo = update.message.photo
        audio = update.message.audio

        attachment_path = None
        filename = "file"

        if document:
            file = await document.get_file()
            filename = document.file_name or "file"
            attachment_path = await attachments_service.download_telegram(
                file, session.id, filename
            )
        elif photo:
            file = await photo[-1].get_file()
            filename = "image.jpg"
            attachment_path = await attachments_service.download_telegram(
                file, session.id, filename
            )
        elif audio:
            file = await audio.get_file()
            filename = audio.file_name or "audio.mp3"
            attachment_path = await attachments_service.download_telegram(
                file, session.id, filename
            )

        if attachment_path and self._message_handler:
            # Build message with attachment reference
            is_private = update.effective_chat.type == "private"
            attachment_tag = _("[Attachment: {filename}]").format(filename=filename)
            text = f"{caption}\n\n{attachment_tag}" if caption else attachment_tag
            message = Message(
                user_id=user_id,
                username=username,
                text=text,
                attachments=[str(attachment_path)],
                platform="telegram",
                is_group_chat=not is_private,
            )
            user_info = UserInfo(
                user_id=user_id,
                username=username,
                display_name=update.effective_user.first_name,
                platform="telegram",
            )

            thinking_msg = await update.message.reply_text(_("Thinking..."))
            progress_cb, error_cb, tool_cb = self._create_runner_callbacks(thinking_msg)
            try:
                response_text = await self._message_handler(
                    message,
                    user_info,
                    progress_callback=progress_cb,
                    error_callback=error_cb,
                    tool_callback=tool_cb,
                )
                await thinking_msg.delete()

                if response_text.strip():
                    formatted_text = self._convert_tables_to_code_blocks(response_text)
                    chunks = self._split_message(
                        formatted_text, TELEGRAM_MAX_MESSAGE_LENGTH
                    )
                    for chunk in chunks:
                        await self._send_markdown(update, chunk)
            except Exception as e:
                await thinking_msg.delete()
                logger.exception(f"Error processing attachment: {e}")
                await update.message.reply_text(
                    _("Error: {error}").format(error=str(e))
                )

    async def _send_markdown(self, update: Update, text: str) -> None:
        """Send message with Markdown, fallback to plain text on error."""
        try:
            await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.info(f"Markdown parse failed, sending as plain text: {e}")
            await update.message.reply_text(text)

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

    async def execute_scheduled_task(self, user_id: int, prompt: str) -> None:
        """Execute a scheduled task and send result to user."""
        if not self.app or not self._message_handler:
            logger.error(
                "Cannot execute scheduled task: app or handler not initialized"
            )
            return

        username = self._user_usernames.get(user_id)
        message = Message(
            user_id=user_id,
            username=username,
            text=prompt,
            platform="telegram",
        )
        user_info = UserInfo(
            user_id=user_id,
            username=username,
            display_name="Scheduled",
            platform="telegram",
        )

        try:
            # Scheduled memos don't have interactive feedback
            response_text = await self._message_handler(
                message,
                user_info,
                progress_callback=None,
                error_callback=None,
            )

            # Extract and create any follow-up memos
            if self._task_scheduler:
                memos = self._extract_memos(response_text)
                for memo in memos:
                    await self._create_memo_from_tag(user_id, memo)
                response_text = self._remove_memo_tags(response_text)

            # Extract and send files
            files_to_send = self._extract_file_paths(response_text)
            response_text = self._remove_file_tags(response_text)

            formatted_text = f"*Memo*\n\n{response_text}"
            await self.send_message(user_id, formatted_text)

            # Send files as photos or documents
            for file_path in files_to_send:
                await self.send_file(user_id, file_path)

        except Exception as e:
            logger.exception(f"Error executing scheduled task: {e}")

    @staticmethod
    def _is_schedule_request(text: str) -> bool:
        """Check if message is a schedule/memo request."""
        text_lower = text.lower()
        # Must contain a scheduling keyword
        schedule_keywords = [
            "memo",
            "ricordami",
            "ricorda",
            "promemoria",
            "tra ",
            "ogni ",
            "domani alle",
            "stasera alle",
            "oggi alle",
            "stanotte alle",
            "alle ore",
            "schedulami",
            "schedula",
        ]
        return any(kw in text_lower for kw in schedule_keywords)

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
                # Try resolving against known output directories
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

    @staticmethod
    def _strip_markdown_for_tts(text: str) -> str:
        """Strip markdown formatting so TTS reads clean text."""
        # Remove code blocks (``` ... ```)
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove inline code (` ... `)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        # Remove bold/italic markers (**, __, *, _)
        text = re.sub(r"\*{1,2}(.*?)\*{1,2}", r"\1", text)
        text = re.sub(r"_{1,2}(.*?)_{1,2}", r"\1", text)
        # Remove strikethrough (~~text~~)
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        # Remove markdown links [text](url) → text
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Remove headers (# ## ###)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove bullet points (- or *)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        # Collapse multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    async def send_file(
        self,
        user_id: int | str,
        file_path: str,
        caption: str | None = None,
    ) -> bool:
        """Send a file to a chat as photo or document."""
        if not self.app:
            return False

        chat_id = (
            int(user_id) if isinstance(user_id, str) and user_id.isdigit() else user_id
        )

        path = Path(file_path)
        if not path.exists():
            logger.warning(f"File not found: {file_path}")
            return False

        try:
            with open(path, "rb") as f:
                # Send images as photos, others as documents
                if path.suffix.lower() in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    await self.app.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=caption,
                    )
                else:
                    await self.app.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        caption=caption,
                    )
            logger.info(f"Sent file {file_path} to chat {chat_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to send file {file_path}: {e}")
            return False

    @staticmethod
    def _extract_memos(text: str) -> List[dict]:
        """Extract [CREATE_MEMO: type | schedule | title | task] tags from text."""
        memos = []
        # Try 4-part format first: type | schedule | title | task
        pattern_4 = (
            r"\[CREATE_MEMO:\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^\]]+)\]"
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

        # Fallback to 3-part format for backwards compatibility: type | schedule | task
        if not memos:
            pattern_3 = r"\[CREATE_MEMO:\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^\]]+)\]"
            matches = re.findall(pattern_3, text, re.IGNORECASE)
            for match in matches:
                task = match[2].strip()
                memos.append(
                    {
                        "type": match[0].strip().lower(),
                        "schedule": match[1].strip(),
                        "title": task[:50],  # Use first 50 chars of task as title
                        "task": task,
                    }
                )
        return memos

    @staticmethod
    def _remove_memo_tags(text: str) -> str:
        """Remove [CREATE_MEMO: ...] tags from text."""
        return re.sub(r"\[CREATE_MEMO:[^\]]+\]", "", text, flags=re.IGNORECASE).strip()

    async def _create_memo_from_tag(self, user_id: int, memo: dict) -> int | None:
        """Create a memo/scheduled task from parsed tag.

        Args:
            user_id: User ID
            memo: Dict with type, schedule, title, task

        Returns:
            Memo ID if created, None otherwise
        """
        if not self._task_scheduler:
            return None

        try:
            memo_type = memo.get("type", "once")
            schedule = memo.get("schedule", "")
            title = memo.get("title", "")
            task = memo.get("task", "")

            if memo_type == "cron":
                # Recurring memo with cron expression
                memo_id = await self._task_scheduler.add_memo(
                    user_id=user_id,
                    platform="telegram",
                    schedule_type="cron",
                    prompt=task,
                    description=title,  # Title becomes the prompt title
                    cron=schedule,
                )
                logger.info(
                    f"Created recurring memo {memo_id} for user {user_id}: {title} ({schedule})"
                )
                return memo_id
            else:
                # One-time memo with datetime
                from datetime import datetime
                from zoneinfo import ZoneInfo

                # Parse ISO datetime
                run_at = datetime.fromisoformat(schedule)
                if run_at.tzinfo is None:
                    run_at = run_at.replace(tzinfo=ZoneInfo("Europe/Rome"))

                memo_id = await self._task_scheduler.add_memo(
                    user_id=user_id,
                    platform="telegram",
                    schedule_type="once",
                    prompt=task,
                    description=title,  # Title becomes the prompt title
                    run_at=run_at,
                )
                logger.info(
                    f"Created one-time memo {memo_id} for user {user_id}: {title} ({run_at})"
                )
                return memo_id

        except Exception as e:
            logger.error(f"Failed to create memo from tag: {e}")
