from cognitive_world.runtime import SimulationClock


def test_simulation_clock_can_be_created():
    clock = SimulationClock()

    assert clock.current_time == 0


def test_tick_advances_time_by_one_unit():
    clock = SimulationClock()

    assert clock.tick() == 1
    assert clock.current_time == 1


def test_advance_moves_time_by_the_requested_amount():
    clock = SimulationClock()

    assert clock.advance(5) == 5
    assert clock.current_time == 5


def test_clocks_keep_independent_time_state():
    first = SimulationClock()
    second = SimulationClock()

    first.advance(3)

    assert first.current_time == 3
    assert second.current_time == 0
