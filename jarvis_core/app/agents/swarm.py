import operator
from typing import Dict, List, Annotated, TypedDict
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, END

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    intent_classification: str
    target_deliverable_spec: str
    execution_errors: List[str]

# Separate model targets via fast network routing mesh
router_llm = ChatOpenAI(model="llama3.1:8b", base_url="http://localhost:11434/v1", api_key="ollama")
heavy_llm = ChatOpenAI(model="qwen2.5-coder:32b", base_url="http://localhost:11434/v1", api_key="ollama")

def intent_classifier_gate(state: AgentState) -> Dict:
    """Evaluates payload input strings to distribute tracking to specialized lanes."""
    last_message = state["messages"][-1].content

    prompt = f"Classify this query. Respond with exactly 'CORPORATE' or 'GENERAL_ORACLE'. Query: {last_message}"
    response = router_llm.invoke([HumanMessage(content=prompt)])

    classification = "CORPORATE" if "CORPORATE" in response.content.upper() else "GENERAL_ORACLE"
    return {"intent_classification": classification}

def execute_corporate_swarm(state: AgentState) -> Dict:
    """Manages active enterprise CRM logs and coordinates custom agent compilations."""
    last_query = state["messages"][-1].content
    response = heavy_llm.invoke([HumanMessage(content=f"Process corporate task requirements: {last_query}")])
    return {"messages": [AIMessage(content=response.content)]}

def execute_oracle_branch(state: AgentState) -> Dict:
    """Bypasses business tools to return high-precision text responses from model weights."""
    last_query = state["messages"][-1].content
    response = heavy_llm.invoke([HumanMessage(content=last_query)])
    return {"messages": [AIMessage(content=response.content)]}

def router_conditional_edge(state: AgentState) -> str:
    if state["intent_classification"] == "CORPORATE":
        return "corporate_swarm"
    return "oracle_branch"

workflow = StateGraph(AgentState)
workflow.add_node("classifier", intent_classifier_gate)
workflow.add_node("corporate_swarm", execute_corporate_swarm)
workflow.add_node("oracle_branch", execute_oracle_branch)

workflow.set_entry_point("classifier")
workflow.add_conditional_edges("classifier", router_conditional_edge)
workflow.add_edge("corporate_swarm", END)
workflow.add_edge("oracle_branch", END)

compiled_ira_brain = workflow.compile()
