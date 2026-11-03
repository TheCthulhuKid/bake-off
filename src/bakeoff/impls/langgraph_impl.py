"""LangGraph version: a fetch, analyse and report graph over the shared tools."""

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from bakeoff.contract import TriageReport
from bakeoff.prompt import REPORT_PROMPT, SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_usage
from bakeoff.tools import get_issue, list_issues, search_issues

TOOLS = [list_issues, get_issue, search_issues]


class State(MessagesState):
    answer: AIMessage
    triage_report: TriageReport


def build_graph(model: BaseChatModel) -> CompiledStateGraph:
    """The fetch, analyse and report graph over ``model``; tests pass a scripted one."""
    fetch_model = model.bind_tools(TOOLS)
    # The same tools as fetch: the API rejects fetch's thinking blocks under a different tools
    # list. tool_choice "none" stops tool calls, and response_format sends the report schema.
    analyse_model = model.bind_tools(
        TOOLS, tool_choice={"type": "none"}, response_format=TriageReport
    )

    def fetch(state: State) -> dict[str, Any]:
        return {"messages": [fetch_model.invoke(state["messages"])]}

    def analyse(state: State) -> dict[str, Any]:
        messages = [*state["messages"], HumanMessage(REPORT_PROMPT)]
        return {"answer": analyse_model.invoke(messages)}

    def report(state: State) -> dict[str, Any]:
        return {"triage_report": TriageReport.model_validate_json(state["answer"].text)}

    graph = StateGraph(State)
    graph.add_node("fetch", fetch)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("analyse", analyse)
    graph.add_node("report", report)
    graph.add_edge(START, "fetch")
    graph.add_conditional_edges("fetch", tools_condition, {"tools": "tools", END: "analyse"})
    graph.add_edge("tools", "fetch")
    graph.add_edge("analyse", "report")
    graph.add_edge("report", END)
    return graph.compile()


graph = build_graph(
    ChatAnthropic(model=SETTINGS.model, api_key=SETTINGS.anthropic_api_key, effort=SETTINGS.effort)
)


def triage(repo: str) -> TriageReport:
    """Run the graph on ``repo`` and return its report."""
    usage = UsageMetadataCallbackHandler()
    messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(user_prompt(repo))]
    try:
        state = graph.invoke({"messages": messages}, config={"callbacks": [usage]})
        return state["triage_report"]
    finally:
        for counts in usage.usage_metadata.values():
            record_usage(counts["input_tokens"], counts["output_tokens"])
