from app.services.agent_loop import AgentLoop


def test_simple_request_uses_fast_path() -> None:
    decision = AgentLoop().decide("Привет, как дела?")
    assert decision.mode == "fast"
    assert decision.max_iterations == 1


def test_complex_request_gets_agent_contract() -> None:
    loop = AgentLoop()
    decision = loop.decide("Разбери BUD и найди слабые места")
    assert decision.mode == "agent"
    assert decision.max_iterations == 3
    rendered = loop.augment_instructions("base", "Разбери BUD")
    assert "Autonomous task contract" in rendered


def test_fast_path_does_not_change_instructions() -> None:
    loop = AgentLoop()
    assert loop.augment_instructions("base", "Привет") == "base"
