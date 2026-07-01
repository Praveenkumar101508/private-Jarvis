"""Answer-quality — rule-based answer verification (no model call)."""
from reasoning.answer_policy import TASK_CODING, TASK_GENERAL, TASK_RESEARCH, get_policy
from reasoning.answer_verifier import (
    ISSUE_MISSING_CITATION,
    ISSUE_MISSING_TEST_STEP,
    ISSUE_OFF_TOPIC,
    ISSUE_TOO_VAGUE,
    ISSUE_UNSAFE_EXTERNAL,
    ISSUE_UNSTATED_ASSUMPTIONS,
    verify_answer,
)

_GOOD_CODE_ANSWER = (
    "Root cause: the loop reads `items[i+1]` past the end of the list.\n\n"
    "```python\n"
    "def process(items):\n"
    "    for i in range(len(items) - 1):\n"
    "        handle(items[i], items[i + 1])\n"
    "```\n\n"
    "Run `pytest tests/test_process.py` to verify the fix and confirm no "
    "IndexError is raised on a two-item list."
)


def test_solid_answer_passes():
    result = verify_answer(
        "debug this function, it crashes with an IndexError",
        _GOOD_CODE_ANSWER,
        task_type=TASK_CODING,
        policy=get_policy(TASK_CODING),
    )
    assert result.passed
    assert result.issues == ()


def test_catches_vague_short_answer():
    result = verify_answer("explain how the caching layer works", "It depends.", task_type=TASK_GENERAL)
    assert not result.passed
    assert result.has(ISSUE_TOO_VAGUE)


def test_catches_hedging_as_vague_even_if_long():
    long_hedge = "It depends on a lot of different things and factors that vary quite a bit honestly."
    result = verify_answer("what database should I use", long_hedge, task_type=TASK_GENERAL)
    assert result.has(ISSUE_TOO_VAGUE)


def test_catches_missing_test_verification_for_code_answer():
    code_no_test = (
        "Here's the fix:\n\n```python\ndef process(items):\n    return items[:-1]\n```\n"
        "That should handle the off-by-one issue you described nicely."
    )
    result = verify_answer(
        "debug this function that throws an IndexError",
        code_no_test,
        task_type=TASK_CODING,
        policy=get_policy(TASK_CODING),
    )
    assert result.has(ISSUE_MISSING_TEST_STEP)


def test_code_answer_with_test_mention_does_not_flag_missing_test():
    result = verify_answer(
        "debug this function that throws an IndexError",
        _GOOD_CODE_ANSWER,
        task_type=TASK_CODING,
        policy=get_policy(TASK_CODING),
    )
    assert not result.has(ISSUE_MISSING_TEST_STEP)


def test_catches_missing_citation_for_research_task():
    no_source = (
        "Quantum computers can outperform classical ones on certain factoring "
        "problems using Shor's algorithm, which runs in polynomial time on a "
        "large enough fault-tolerant machine."
    )
    result = verify_answer(
        "research the latest sources on quantum computing breakthroughs",
        no_source,
        task_type=TASK_RESEARCH,
        policy=get_policy(TASK_RESEARCH),
    )
    assert result.has(ISSUE_MISSING_CITATION)


def test_research_answer_with_source_does_not_flag_citation():
    with_source = (
        "According to https://arxiv.org/abs/2301.00000, error-corrected qubits "
        "crossed the surface-code threshold in 2025."
    )
    result = verify_answer(
        "research the latest sources on quantum computing breakthroughs",
        with_source,
        task_type=TASK_RESEARCH,
        policy=get_policy(TASK_RESEARCH),
    )
    assert not result.has(ISSUE_MISSING_CITATION)


def test_catches_off_topic_answer():
    result = verify_answer(
        "what is the capital of france",
        "Bananas are a great source of potassium and make a healthy snack.",
        task_type=TASK_GENERAL,
    )
    assert result.has(ISSUE_OFF_TOPIC)


def test_catches_unsafe_external_use_without_consent():
    result = verify_answer(
        "do a very deep architecture review",
        "Here is a thorough architecture review with detailed trade-offs and risks laid out.",
        provider="external",
        consent_approved=None,
    )
    assert result.has(ISSUE_UNSAFE_EXTERNAL)


def test_external_use_with_recorded_consent_is_not_flagged():
    result = verify_answer(
        "do a very deep architecture review",
        "Here is a thorough architecture review with detailed trade-offs and risks laid out.",
        provider="external",
        consent_approved=True,
    )
    assert not result.has(ISSUE_UNSAFE_EXTERNAL)


def test_local_provider_is_never_flagged_unsafe():
    result = verify_answer(
        "hello there",
        "Hi! How can I help you today with something specific?",
        provider="local",
        consent_approved=None,
    )
    assert not result.has(ISSUE_UNSAFE_EXTERNAL)


def test_catches_unstated_assumptions_on_ambiguous_prompt():
    result = verify_answer(
        "what's the best database for my app",
        "Postgres is a solid, reliable choice for most applications overall.",
        task_type=TASK_GENERAL,
    )
    assert result.has(ISSUE_UNSTATED_ASSUMPTIONS)


def test_stating_assumption_clears_the_flag():
    result = verify_answer(
        "what's the best database for my app",
        "Assuming you need strong relational consistency, Postgres is a solid choice "
        "for most applications and scales well for typical workloads.",
        task_type=TASK_GENERAL,
    )
    assert not result.has(ISSUE_UNSTATED_ASSUMPTIONS)
