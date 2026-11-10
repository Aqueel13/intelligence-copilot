"""Working-hours calendar arithmetic. All datetimes are naive local time (IST has no DST)."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

_DAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass(frozen=True)
class WorkCalendar:
    workdays: frozenset[int]
    start: time
    end: time

    @classmethod
    def from_config(cls, workdays: list[str], start: str, end: str) -> "WorkCalendar":
        return cls(
            workdays=frozenset(_DAY_INDEX[d] for d in workdays),
            start=time.fromisoformat(start),
            end=time.fromisoformat(end),
        )

    def is_working(self, dt: datetime) -> bool:
        return dt.weekday() in self.workdays and self.start <= dt.time() < self.end

    def next_working_moment(self, dt: datetime) -> datetime:
        """`dt` itself if inside working hours, else the start of the next working period."""
        if dt.weekday() in self.workdays:
            if dt.time() < self.start:
                return datetime.combine(dt.date(), self.start)
            if dt.time() < self.end:
                return dt
        day = dt.date() + timedelta(days=1)
        while day.weekday() not in self.workdays:
            day += timedelta(days=1)
        return datetime.combine(day, self.start)

    def add_working_hours(self, dt: datetime, hours: float) -> datetime:
        """Move forward by `hours` of working time, skipping nights and non-working days."""
        current = self.next_working_moment(dt)
        remaining = timedelta(hours=max(hours, 0.0))
        while True:
            day_end = datetime.combine(current.date(), self.end)
            available = day_end - current
            if remaining <= available:
                return current + remaining
            remaining -= available
            current = self.next_working_moment(day_end)

    def next_workday_start(self, dt: datetime) -> datetime:
        """Start of the first working day strictly after `dt`'s date."""
        return self.next_working_moment(datetime.combine(dt.date(), self.end))
