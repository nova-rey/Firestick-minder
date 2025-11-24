from firestick_minder import IdleState, update_idle_state


def test_idle_resets_when_media_playing():
    state = IdleState(idle_seconds=30)
    state, should_launch, idle_eligible = update_idle_state(
        state=state,
        home_screen=True,
        in_target_app=False,
        media_playing=True,
        poll_interval=5,
        timeout=60,
    )

    assert idle_eligible is False
    assert should_launch is False
    assert state.idle_seconds == 0


def test_idle_resets_in_target_app():
    state = IdleState(idle_seconds=30)
    state, should_launch, idle_eligible = update_idle_state(
        state=state,
        home_screen=False,
        in_target_app=True,
        media_playing=False,
        poll_interval=5,
        timeout=60,
    )

    assert idle_eligible is False
    assert should_launch is False
    assert state.idle_seconds == 0


def test_idle_accumulates_on_quiet_home():
    state = IdleState(idle_seconds=10)
    state, should_launch, idle_eligible = update_idle_state(
        state=state,
        home_screen=True,
        in_target_app=False,
        media_playing=False,
        poll_interval=5,
        timeout=60,
    )

    assert idle_eligible is True
    assert should_launch is False
    assert state.idle_seconds == 15


def test_launch_only_when_not_in_target_app_and_idle_over_timeout():
    state = IdleState(idle_seconds=55)
    state, should_launch, idle_eligible = update_idle_state(
        state=state,
        home_screen=True,
        in_target_app=False,
        media_playing=False,
        poll_interval=5,
        timeout=60,
    )

    assert idle_eligible is True
    assert should_launch is True
    assert state.idle_seconds == 0

    state = IdleState(idle_seconds=55)
    state, should_launch, idle_eligible = update_idle_state(
        state=state,
        home_screen=True,
        in_target_app=True,
        media_playing=False,
        poll_interval=5,
        timeout=60,
    )

    assert idle_eligible is False
    assert should_launch is False
    assert state.idle_seconds == 0
