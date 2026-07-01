"""Answer-quality — task-specific answer policy selection."""
from reasoning.answer_policy import (
    TASK_ARCHITECTURE,
    TASK_CODING,
    TASK_DEBUGGING,
    TASK_GENERAL,
    TASK_JOB_APPLICATION,
    TASK_PLANNING,
    TASK_RESEARCH,
    TASK_REWRITE,
    TASK_SIMPLE_QUESTION,
    classify_task_type,
    get_policy,
    local_fallback_notice,
    policy_for_prompt,
)
from reasoning.model_profiles import ModelMode
from reasoning.model_router import ModelRouteDecision


def test_rewrite_email_routes_to_polished_final_text_policy():
    task = classify_task_type("please rewrite this email to sound more professional")
    assert task == TASK_REWRITE
    policy = get_policy(task)
    assert "final" in policy.instructions.lower()


def test_coding_routes_to_code_explanation_tests_policy():
    task = classify_task_type("implement a function that parses this file")
    assert task == TASK_CODING
    policy = get_policy(task)
    assert policy.requires_test_step is True


def test_architecture_routes_to_structured_risks_next_steps_policy():
    task = classify_task_type("design a scalable system architecture for our SaaS")
    assert task == TASK_ARCHITECTURE
    policy = get_policy(task)
    assert "risks" in policy.instructions.lower()
    assert "next steps" in policy.instructions.lower()


def test_job_application_routes_to_concise_professional_policy():
    task = classify_task_type("help me write a cover letter for this job application")
    assert task == TASK_JOB_APPLICATION
    policy = get_policy(task)
    assert "professional" in policy.instructions.lower()


def test_research_routes_to_citation_policy():
    task = classify_task_type("research the latest sources on quantum computing")
    assert task == TASK_RESEARCH
    policy = get_policy(task)
    assert policy.requires_citation is True


def test_debugging_routes_to_root_cause_fix_verification_policy():
    task = classify_task_type("debug this stack trace, it keeps throwing an exception")
    assert task == TASK_DEBUGGING
    policy = get_policy(task)
    assert "root cause" in policy.instructions.lower()
    assert policy.requires_test_step is True


def test_planning_routes_to_phases_priorities_policy():
    task = classify_task_type("give me a roadmap with phases and milestones for this project")
    assert task == TASK_PLANNING
    policy = get_policy(task)
    assert "phases" in policy.instructions.lower() or "priority" in policy.instructions.lower()


def test_short_prompt_routes_to_simple_question_policy():
    task = classify_task_type("what time is it")
    assert task == TASK_SIMPLE_QUESTION
    policy = get_policy(task)
    assert "short" in policy.instructions.lower()


def test_unmatched_longer_prompt_routes_to_general():
    task = classify_task_type("Tell me a bit about how coffee is generally grown and processed")
    assert task == TASK_GENERAL


def test_policy_for_prompt_matches_classify_then_get():
    prompt = "debug why this endpoint keeps throwing an exception"
    assert policy_for_prompt(prompt) is get_policy(classify_task_type(prompt))


def test_unknown_task_type_never_raises():
    policy = get_policy("totally-made-up-task-type")
    assert policy.task_type == TASK_GENERAL


# ── Local fallback framing ──────────────────────────────────────────────────

def _decision(mode: ModelMode, requires_api_consent: bool = False) -> ModelRouteDecision:
    return ModelRouteDecision(
        selected_mode=mode,
        selected_model="some-model",
        fallback_model=None,
        reason="test",
        confidence=0.5,
        requires_api_consent=requires_api_consent,
        estimated_cost_level="none",
        privacy_level="local_first",
        allow_local_fallback=True,
        provider="local",
    )


def test_no_notice_when_not_degraded_to_tiny():
    assert local_fallback_notice(_decision(ModelMode.LOCAL_MAIN)) is None


def test_notice_says_continuing_in_local_mode_not_weak():
    note = local_fallback_notice(_decision(ModelMode.FALLBACK_TINY))
    assert note is not None
    assert "Continuing in Local Mode" in note
    assert "weak" not in note.lower()


def test_notice_suggests_deep_mode_only_when_task_needs_it():
    plain = local_fallback_notice(_decision(ModelMode.FALLBACK_TINY, requires_api_consent=False))
    hard = local_fallback_notice(_decision(ModelMode.FALLBACK_TINY, requires_api_consent=True))
    assert "Deep Intelligence Mode" not in plain
    assert "Deep Intelligence Mode" in hard
