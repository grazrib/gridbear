import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Rome")


@dataclass
class ParsedSchedule:
    schedule_type: str  # "cron" or "once"
    cron: str | None = None  # For recurring: "minute hour day month weekday"
    run_at: datetime | None = None  # For one-time
    prompt: str = ""
    description: str = ""


class ScheduleParser:
    """Parse natural language schedule expressions to cron format (IT/EN)."""

    # Italian weekdays
    WEEKDAYS_IT = {
        "lunedì": 0,
        "lunedi": 0,
        "lun": 0,
        "martedì": 1,
        "martedi": 1,
        "mar": 1,
        "mercoledì": 2,
        "mercoledi": 2,
        "mer": 2,
        "giovedì": 3,
        "giovedi": 3,
        "gio": 3,
        "venerdì": 4,
        "venerdi": 4,
        "ven": 4,
        "sabato": 5,
        "sab": 5,
        "domenica": 6,
        "dom": 6,
    }

    # English weekdays
    WEEKDAYS_EN = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "tues": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }

    @classmethod
    def parse(cls, text: str) -> ParsedSchedule | None:
        """Parse natural language schedule to structured format."""
        text_lower = text.lower().strip()

        # Try one-time schedule first
        result = cls._parse_once(text_lower, text)
        if result:
            return result

        # Try recurring schedule
        result = cls._parse_recurring(text_lower, text)
        if result:
            return result

        return None

    @classmethod
    def _parse_once(cls, text_lower: str, original: str) -> ParsedSchedule | None:
        """Parse one-time schedules."""
        now = datetime.now(TIMEZONE)

        # ITALIAN: "tra X minuti/ore"
        match = re.search(r"tra\s+(\d+)\s+(minut[oi]|or[ae])", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if "minut" in unit:
                run_at = now + timedelta(minutes=amount)
            else:
                run_at = now + timedelta(hours=amount)
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"Once at {run_at.strftime('%H:%M %d/%m')}",
            )

        # ENGLISH: "in X minutes/hours"
        match = re.search(r"in\s+(\d+)\s+(minutes?|hours?)", text_lower)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            if "minute" in unit:
                run_at = now + timedelta(minutes=amount)
            else:
                run_at = now + timedelta(hours=amount)
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"Once at {run_at.strftime('%H:%M %d/%m')}",
            )

        # ITALIAN: "domani alle HH:MM"
        match = re.search(r"domani\s+alle?\s+(\d{1,2})(?::(\d{2}))?", text_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            run_at = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"Tomorrow at {hour:02d}:{minute:02d}",
            )

        # ENGLISH: "tomorrow at HH:MM"
        match = re.search(r"tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?", text_lower)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2)) if match.group(2) else 0
            run_at = (now + timedelta(days=1)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"Tomorrow at {hour:02d}:{minute:02d}",
            )

        # ITALIAN: "oggi/stasera/stanotte alle HH:MM"
        match = re.search(
            r"(oggi|stasera|stanotte)\s+alle?\s+(\d{1,2})(?::(\d{2}))?", text_lower
        )
        if match:
            when = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now:
                run_at = run_at + timedelta(days=1)
            prompt = cls._extract_prompt(text_lower, match.end())
            desc = {"oggi": "Today", "stasera": "Tonight", "stanotte": "Tonight"}.get(
                when, "Today"
            )
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"{desc} at {hour:02d}:{minute:02d}",
            )

        # ENGLISH: "today/tonight at HH:MM"
        match = re.search(r"(today|tonight)\s+at\s+(\d{1,2})(?::(\d{2}))?", text_lower)
        if match:
            when = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if run_at <= now:
                run_at = run_at + timedelta(days=1)
            prompt = cls._extract_prompt(text_lower, match.end())
            desc = "Today" if when == "today" else "Tonight"
            return ParsedSchedule(
                schedule_type="once",
                run_at=run_at,
                prompt=prompt,
                description=f"{desc} at {hour:02d}:{minute:02d}",
            )

        return None

    @classmethod
    def _parse_recurring(cls, text_lower: str, original: str) -> ParsedSchedule | None:
        """Parse recurring schedules."""

        # ITALIAN: "ogni giorno/mattina/sera/pomeriggio alle HH:MM"
        match = re.search(
            r"ogni\s+(giorno|mattina|mattino|sera|pomeriggio)\s+alle?\s+(\d{1,2})(?::(\d{2}))?",
            text_lower,
        )
        if match:
            time_of_day = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            cron = f"{minute} {hour} * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            desc_map = {
                "giorno": "day",
                "mattina": "morning",
                "mattino": "morning",
                "sera": "evening",
                "pomeriggio": "afternoon",
            }
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {desc_map.get(time_of_day, 'day')} at {hour:02d}:{minute:02d}",
            )

        # ENGLISH: "every day/morning/evening/afternoon at HH:MM"
        match = re.search(
            r"every\s+(day|morning|evening|afternoon|night)\s+at\s+(\d{1,2})(?::(\d{2}))?",
            text_lower,
        )
        if match:
            time_of_day = match.group(1)
            hour = int(match.group(2))
            minute = int(match.group(3)) if match.group(3) else 0
            cron = f"{minute} {hour} * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {time_of_day} at {hour:02d}:{minute:02d}",
            )

        # ITALIAN: "ogni [weekday] alle HH:MM"
        for day_name, day_num in cls.WEEKDAYS_IT.items():
            pattern = rf"ogni\s+{day_name}\s+alle?\s+(\d{{1,2}})(?::(\d{{2}}))?"
            match = re.search(pattern, text_lower)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if match.group(2) else 0
                cron = f"{minute} {hour} * * {day_num}"
                prompt = cls._extract_prompt(text_lower, match.end())
                return ParsedSchedule(
                    schedule_type="cron",
                    cron=cron,
                    prompt=prompt,
                    description=f"Every {day_name.capitalize()} at {hour:02d}:{minute:02d}",
                )

        # ENGLISH: "every [weekday] at HH:MM"
        for day_name, day_num in cls.WEEKDAYS_EN.items():
            pattern = rf"every\s+{day_name}\s+at\s+(\d{{1,2}})(?::(\d{{2}}))?"
            match = re.search(pattern, text_lower)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if match.group(2) else 0
                cron = f"{minute} {hour} * * {day_num}"
                prompt = cls._extract_prompt(text_lower, match.end())
                return ParsedSchedule(
                    schedule_type="cron",
                    cron=cron,
                    prompt=prompt,
                    description=f"Every {day_name.capitalize()} at {hour:02d}:{minute:02d}",
                )

        # ITALIAN: "ogni ora"
        if "ogni ora" in text_lower:
            match = re.search(r"ogni\s+ora", text_lower)
            cron = "0 * * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron", cron=cron, prompt=prompt, description="Every hour"
            )

        # ENGLISH: "every hour"
        if "every hour" in text_lower:
            match = re.search(r"every\s+hour", text_lower)
            cron = "0 * * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron", cron=cron, prompt=prompt, description="Every hour"
            )

        # ITALIAN: "ogni X ore"
        match = re.search(r"ogni\s+(\d+)\s+or[ae]", text_lower)
        if match:
            hours = int(match.group(1))
            cron = f"0 */{hours} * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {hours} hours",
            )

        # ENGLISH: "every X hours"
        match = re.search(r"every\s+(\d+)\s+hours?", text_lower)
        if match:
            hours = int(match.group(1))
            cron = f"0 */{hours} * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {hours} hours",
            )

        # ITALIAN: "ogni X minuti"
        match = re.search(r"ogni\s+(\d+)\s+minut[oi]", text_lower)
        if match:
            minutes = int(match.group(1))
            cron = f"*/{minutes} * * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {minutes} minutes",
            )

        # ENGLISH: "every X minutes"
        match = re.search(r"every\s+(\d+)\s+minutes?", text_lower)
        if match:
            minutes = int(match.group(1))
            cron = f"*/{minutes} * * * *"
            prompt = cls._extract_prompt(text_lower, match.end())
            return ParsedSchedule(
                schedule_type="cron",
                cron=cron,
                prompt=prompt,
                description=f"Every {minutes} minutes",
            )

        return None

    @classmethod
    def _extract_prompt(cls, text: str, start_pos: int) -> str:
        """Extract the prompt/task from the remaining text."""
        remaining = text[start_pos:].strip()
        # Remove common connecting words (IT + EN)
        prefixes = [
            # Italian
            "dimmi",
            "fammi",
            "mandami",
            "inviami",
            "controlla",
            "verifica",
            "di ",
            "a ",
            "che ",
            # English
            "tell me",
            "send me",
            "remind me",
            "to ",
            "that ",
        ]
        for prefix in prefixes:
            if remaining.startswith(prefix):
                remaining = remaining[len(prefix) :].strip()
                break
        return remaining.strip(" ,.")
