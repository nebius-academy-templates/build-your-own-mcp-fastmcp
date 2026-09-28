"""Task 3: the triage prompt, the instructions and version 0.4.0."""

from __future__ import annotations

import re

import pytest

from support import (
    P1_INSTRUCTIONS, P3_SENTENCE, P4_SENTENCE, PROMPT, VIEWER, corpus_names, p2_sentence, rpc_error,
    stdio_session,
)

TASK = "Task 3 adds the triage prompt."
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def version_tuple(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    assert match, f"the server version must look like 0.4.0, got {text!r}"
    return tuple(int(part) for part in match.groups())


@pytest.fixture(scope="module")
def over_stdio(tmp_path_factory):
    """What the server says about itself over stdio: version, instructions, prompt names."""
    async def work(client):
        prompts = await client.list_prompts()
        return {"version": client.server_info.version, "instructions": client.instructions,
                "prompts": [prompt.name for prompt in prompts]}

    return stdio_session(work, "--reports", str(tmp_path_factory.mktemp("reports")))


def test_server_version_is_at_least_0_4_0(over_stdio):
    version = over_stdio["version"]
    assert version_tuple(version) >= (0, 4, 0), f"the server version must be 0.4.0 or later, got {version!r}. {TASK}"


def test_instructions_add_the_prompt_sentence(over_stdio):
    text = over_stdio["instructions"] or ""
    want = f"{P1_INSTRUCTIONS} {p2_sentence('15 minutes')} {P3_SENTENCE} {P4_SENTENCE}"
    assert text == want, (
        "instructions must be the practice 3 text, a space, and the prompt sentence of CONTRACT.md, section 8.\n"
        f"expected: {want!r}\ngot:      {text!r}"
    )
    assert len(text) <= 1000, f"instructions must be at most 1,000 characters, got {len(text)}"


def test_the_prompt_is_there_over_stdio(over_stdio):
    assert PROMPT["name"] in over_stdio["prompts"], (
        f"prompts/list over stdio must hold {PROMPT['name']}; got {over_stdio['prompts']}. {TASK}"
    )


def triage_of(server, token=None) -> dict:
    prompts = server.prompts(token) if token else server.prompts()
    found = [prompt for prompt in prompts if prompt.get("name") == PROMPT["name"]]
    assert found, f"prompts/list over HTTP must hold {PROMPT['name']}; got {[p.get('name') for p in prompts]}. {TASK}"
    return found[0]


def test_the_prompt_and_its_arguments(server):
    prompt = triage_of(server)
    assert (prompt.get("description") or "").strip(), "the triage prompt needs a description"
    got = [(arg.get("name"), bool(arg.get("required"))) for arg in prompt.get("arguments") or []]
    want = [(arg["name"], arg["required"]) for arg in PROMPT["arguments"]]
    assert sorted(got) == sorted(want), (
        f"the triage prompt's arguments and required flags must be {want} (CONTRACT.md, section 5); got {got}"
    )
    for arg in prompt.get("arguments") or []:
        assert (arg.get("description") or "").strip(), f"the argument {arg.get('name')} needs a description"


def rendered_text(server, arguments: dict, token=None) -> str:
    result = server.get_prompt(arguments, token) if token else server.get_prompt(arguments)
    messages = result.get("messages") or []
    assert len(messages) == 1, f"the rendered prompt must be one message, got {len(messages)}"
    message = messages[0]
    assert message.get("role") == "user", f"the rendered prompt's message must have role user, got {message.get('role')!r}"
    content = message.get("content") or {}
    assert content.get("type") == "text" and content.get("text"), "the rendered prompt must be one text content"
    return content["text"]


def check_tool_order(text: str) -> None:
    positions = []
    for name in PROMPT["tool_order"]:
        found = re.search(rf"\b{re.escape(name)}\b", text)
        assert found, f"the rendered prompt must name {name} (CONTRACT.md, section 5)"
        positions.append((found.start(), name))
    order = [name for _, name in sorted(positions)]
    assert order == PROMPT["tool_order"], (
        f"the rendered prompt must first name the tools in the order {PROMPT['tool_order']}; "
        f"their first mentions come in the order {order}"
    )


def check_no_corpus_names(text: str) -> None:
    hits = sorted(name for name in corpus_names() if name in text)
    assert not hits, f"the rendered prompt names hosts or dates from s3_logs: {hits}"
    addresses = IPV4.findall(text)
    assert not addresses, f"the rendered prompt names addresses: {addresses}"


def test_the_rendered_prompt_with_every_argument(server):
    arguments = PROMPT["render"]
    text = rendered_text(server, arguments)
    for name, value in arguments.items():
        assert value in text, f"the rendered prompt must repeat the {name} it was given, {value!r}"
    check_tool_order(text)
    check_no_corpus_names(text)


def test_the_rendered_prompt_with_the_symptom_only(server):
    arguments = PROMPT["render_symptom_only"]
    text = rendered_text(server, arguments)
    assert arguments["symptom"] in text, "the rendered prompt must repeat the symptom it was given"
    check_tool_order(text)
    check_no_corpus_names(text)


def test_the_read_only_caller_gets_the_prompt(server):
    triage_of(server, VIEWER)
    assert PROMPT["render_symptom_only"]["symptom"] in rendered_text(server, PROMPT["render_symptom_only"], VIEWER)


def test_a_missing_symptom_is_refused(server):
    triage_of(server)
    raw = server.rpc("prompts/get", {"name": PROMPT["name"], "arguments": {"path": "hosts/example-7"}})
    rpc_error(raw, "symptom is required")


def test_an_unknown_prompt_is_refused(server):
    raw = server.rpc("prompts/get", {"name": "no-such-prompt", "arguments": {}})
    rpc_error(raw, "the server has no such prompt")
