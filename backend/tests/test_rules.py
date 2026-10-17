"""Pure formulas from CONTRACTS sections 6 and 10."""
from backend.app.risk import decide, final_outcome, number_score, safety_score


def test_number_score_preflagged_is_92():
    # 45 * 0.82 + 3 flags + 6 users in 24 h + short calls + odd hours = 91.9 -> 92
    assert number_score(0.82, 3, 6, 6, 6, False) == 92


def test_number_score_caps_and_clamps():
    assert number_score(1.0, 10, 9, 9, 9, False) == 100  # flags capped at 30
    assert number_score(0.0, 0, 0, 0, 0, True) == 0      # verified penalty floors at 0
    assert number_score(0.9, 1, 0, 0, 0, True) == 11     # 40.5 + 10 - 40 = 10.5, rounds half up


def test_number_score_thresholds():
    assert number_score(users_24h=4) == 0
    assert number_score(users_24h=5) == 10
    assert number_score(short_calls_24h=3) == 10
    assert number_score(odd_hour_calls_24h=1) == 5


def test_decide_table():
    assert decide(0.70, 1, 5) == "end"
    assert decide(0.69, 1, 5) == "continue"
    assert decide(0.39, 3, 20) == "connect"
    assert decide(0.40, 3, 20) == "message"
    assert decide(0.1, 1, 60) == "connect"
    assert decide(0.5, 0, 90) == "message"


def test_final_outcome():
    assert final_outcome(0.8) == "ended_scam"
    assert final_outcome(0.2) == "message"


def test_safety_score():
    assert safety_score() == 100
    assert safety_score(1, 2, 1) == 60
    assert safety_score(5, 5, 5) == 0
