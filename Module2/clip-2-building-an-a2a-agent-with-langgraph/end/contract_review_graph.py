"""Contract Review Agent - LangGraph.

A stateful graph that analyzes contract text and flags risk clauses.
Uses a two-node graph: extract key terms, then assess risk.
"""

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, MessagesState, StateGraph

load_dotenv()

llm = ChatOpenAI(model="gpt-5.4-nano", temperature=0)


def extract_clauses(state: MessagesState) -> dict:
    """Node 1: Extract key clauses from the contract text."""
    messages = state["messages"]
    system_msg = {
        "role": "system",
        "content": (
            "You are a contract analyst. Extract and list the key clauses "
            "from the contract text provided. For each clause, state the "
            "clause type and a one-sentence summary. Be concise."
        ),
    }
    response = llm.invoke([system_msg] + messages)
    return {"messages": [response]}


def assess_risk(state: MessagesState) -> dict:
    """Node 2: Assess risk based on the extracted clauses."""
    messages = state["messages"]
    system_msg = {
        "role": "system",
        "content": (
            "You are a contract risk assessor. Based on the clause extraction "
            "above, provide a risk assessment. Rate overall risk as LOW, "
            "MEDIUM, or HIGH. For each flagged clause, explain the risk in "
            "one sentence. End with a recommendation."
        ),
    }
    response = llm.invoke([system_msg] + messages)
    return {"messages": [response]}


# Build the graph
graph = StateGraph(MessagesState)
graph.add_node("extract_clauses", extract_clauses)
graph.add_node("assess_risk", assess_risk)
graph.add_edge(START, "extract_clauses")
graph.add_edge("extract_clauses", "assess_risk")
graph.add_edge("assess_risk", END)

contract_review_graph = graph.compile()
