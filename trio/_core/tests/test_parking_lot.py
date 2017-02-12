import pytest

from ... import _core
from ...testing import busy_wait_for
from .test_util import check_sequence_matches
from .._parking_lot import ParkingLot

async def test_parking_lot_basic():
    record = []
    async def waiter(i, lot):
        record.append("sleep {}".format(i))
        val = await lot.park()
        record.append("wake {} = {}".format(i, val))

    async with _core.open_nursery() as nursery:
        lot = ParkingLot()
        assert lot.statistics().tasks_waiting == 0
        for i in range(3):
            nursery.spawn(waiter, i, lot)
        await busy_wait_for(lambda: len(record) == 3)
        assert lot.statistics().tasks_waiting == 3
        # default is to wake all
        lot.unpark(result=_core.Value(17))
        assert lot.statistics().tasks_waiting == 0
        await busy_wait_for(lambda: len(record) == 6)

    check_sequence_matches(record, [
        {"sleep 0", "sleep 1", "sleep 2"},
        {"wake 0 = 17", "wake 1 = 17", "wake 2 = 17"},
    ])

    async with _core.open_nursery() as nursery:
        record = []
        for i in range(3):
            nursery.spawn(waiter, i, lot)
            await busy_wait_for(lambda: len(record) == 1 + i)
        await busy_wait_for(lambda: len(record) == 3)
        for i in range(3):
            lot.unpark(count=1, result=_core.Value(12))
            await busy_wait_for(lambda: len(record) == 4 + i)
        # 1-by-1 wakeups are strict FIFO
        assert record == [
            "sleep 0", "sleep 1", "sleep 2",
            "wake 0 = 12", "wake 1 = 12", "wake 2 = 12",
        ]

    # It's legal (but a no-op) to try and unpark while there's nothing parked
    lot.unpark()
    lot.unpark(count=1)
    lot.unpark(count=100)

    assert repr(ParkingLot.ALL) == "ParkingLot.ALL"

async def test_parking_lot_cancel():
    record = []

    scopes = {}

    async def waiter(i, lot):
        with _core.open_cancel_scope() as scope:
            scopes[_core.current_task()] = scope
            record.append("sleep {}".format(i))
            try:
                await lot.park()
            except _core.Cancelled:
                record.append("cancelled {}".format(i))
            else:
                record.append("wake {}".format(i))

    async with _core.open_nursery() as nursery:
        lot = ParkingLot()
        w1 = nursery.spawn(waiter, 1, lot)
        await busy_wait_for(lambda: len(record) == 1)
        w2 = nursery.spawn(waiter, 2, lot)
        await busy_wait_for(lambda: len(record) == 2)
        w3 = nursery.spawn(waiter, 3, lot)
        await busy_wait_for(lambda: len(record) == 3)

        scopes[w2].cancel()
        await busy_wait_for(lambda: len(record) == 4)
        lot.unpark(count=ParkingLot.ALL)
        await busy_wait_for(lambda: len(record) == 6)
        await _core.yield_briefly()
        await _core.yield_briefly()
        await _core.yield_briefly()

    check_sequence_matches(record, [
        "sleep 1", "sleep 2", "sleep 3",
        "cancelled 2", {"wake 1", "wake 3"},
    ])