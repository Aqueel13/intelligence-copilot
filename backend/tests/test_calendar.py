from datetime import datetime

from watchdog_backend.generator.calendar import WorkCalendar

CAL = WorkCalendar.from_config(["mon", "tue", "wed", "thu", "fri"], "09:00", "18:00")
# 2026-11-06 is a Friday.
FRI = datetime(2026, 11, 6)


def test_inside_working_hours_is_unchanged() -> None:
    assert CAL.next_working_moment(FRI.replace(hour=10)) == FRI.replace(hour=10)


def test_before_opening_moves_to_opening() -> None:
    assert CAL.next_working_moment(FRI.replace(hour=7)) == FRI.replace(hour=9)


def test_friday_evening_moves_to_monday_morning() -> None:
    assert CAL.next_working_moment(FRI.replace(hour=18)) == datetime(2026, 11, 9, 9)


def test_saturday_moves_to_monday() -> None:
    assert CAL.next_working_moment(datetime(2026, 11, 7, 12)) == datetime(2026, 11, 9, 9)


def test_add_hours_within_a_day() -> None:
    assert CAL.add_working_hours(FRI.replace(hour=9), 3) == FRI.replace(hour=12)


def test_add_hours_spans_the_weekend() -> None:
    # Fri 16:00 + 4 working hours = 2h on Friday + 2h on Monday.
    assert CAL.add_working_hours(FRI.replace(hour=16), 4) == datetime(2026, 11, 9, 11)


def test_add_many_hours_spans_multiple_days() -> None:
    # 9h per day: 20h from Monday 09:00 = Mon (9) + Tue (9) + 2h on Wednesday.
    assert CAL.add_working_hours(datetime(2026, 11, 9, 9), 20) == datetime(2026, 11, 11, 11)


def test_next_workday_start_from_friday() -> None:
    assert CAL.next_workday_start(FRI.replace(hour=15, minute=30)) == datetime(2026, 11, 9, 9)
