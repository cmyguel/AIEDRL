"""LLM agent wrappers used by the simulated tutoring environment."""

from pprint import pprint
from pydantic import BaseModel, Field
from langchain.agents import create_agent
from langchain.messages import SystemMessage, HumanMessage, AIMessage
from langchain_openai import ChatOpenAI

# Model configuration
# MODEL_NAME = "gpt-4.1-nano"
MODEL_STUDENT = "gpt-4.1-mini"
MODEL_GENERAL = "gpt-4.1"

class MyAgent:
    """Stateful LangChain agent with an inspectable conversation history."""

    def __init__(
        self,
        system_message: str,
        model_name: str = MODEL_GENERAL,
        request_timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ):
        self.system_message = system_message
        self.model_name = model_name
        self.request_timeout_seconds = request_timeout_seconds
        self.max_retries = max_retries
        self.agent = self._agent_constructor()
        self.reset_conversation()
    
    def reset_conversation(self):
        # Initialize conversation history with the system message
        self.conversation_history = [SystemMessage(content=self.system_message)]

    def update_system_message(self, system_message: str):
        # Update SystemMessage while keeping the conversation_history intact
        self.system_message = system_message
        self.conversation_history[0] = SystemMessage(content=self.system_message)

    def invoke(self, message: HumanMessage) -> AIMessage:
        self.conversation_history.append(message)
        try:
            response = self.agent.invoke({"messages": self.conversation_history})
            self.conversation_history = response["messages"]  # Update conversation history with the agent's response
        except Exception as error:
            raise RuntimeError(f"Error invoking {self.model_name}: {error}") from error
        
        return self._get_final_message(response)

    def invoke_pprint(self, message: HumanMessage) -> AIMessage:
        out = self.invoke(message=message)
        pprint(out.content)
        return out

    def _get_final_message(self, response: dict) -> AIMessage:
        """
        Extract the final user-facing AI response from a LangChain-style run output.
        Safely skips tool-call placeholders and returns the last meaningful AIMessage.
        """
        
        last_response_message = response["messages"][-1]
        if isinstance(last_response_message, AIMessage) and last_response_message.content:
            return last_response_message
        raise ValueError(
            "No final AIMessage with content found in response. "
            f"Last message type: {type(last_response_message).__name__}"
        )

    def _agent_constructor(self):
        model = ChatOpenAI(
            model=self.model_name,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        agent = create_agent(
            model=model,
            tools=None,
        )
        return agent
    
class Tutor(MyAgent):
    """Tutor agent; defaults to the general paper-run model."""

class StudentOutput(BaseModel):
    """Student structured output"""
    conversation: str = Field(
        description="Student interaction with the tutor"
    )
    python_code: str = Field(
        description="Current student implementation of python solution. Only python code, no comments."
    )

class Student(MyAgent):
    """Synthetic student that returns conversation text and current Python code."""

    def __init__(
        self,
        system_message: str,
        model_name: str = MODEL_STUDENT,
        request_timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ):
        super().__init__(
            system_message,
            model_name=model_name,
            request_timeout_seconds=request_timeout_seconds,
            max_retries=max_retries,
        )

    def invoke(self, message: AIMessage) -> HumanMessage:
        """
        Student receives an AIMessage from the Tutor and responds with a HumanMessage.
        This simulates a student reacting to the tutor's guidance.
        """
        ai_response = super(Student, self).invoke(HumanMessage(content=message.content))
        return HumanMessage(content=ai_response.content)

    def invoke_pprint(self, message: AIMessage) -> HumanMessage:
        out = self.invoke(message=message)
        pprint(out.content)
        return out

    def _agent_constructor(self):
        model = ChatOpenAI(
            model=self.model_name,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        agent_student = create_agent(
            model=model,
            tools=None,
            response_format=StudentOutput,
        )
        return agent_student

class StudentJudgeOutput(BaseModel):
    """StudentJudge structured output"""
    student_level_explanation: str = Field(
        description="Explain why you chose the value for the student level field."
    )
    student_level: int = Field(
        ge=1,
        le=4,
        description="Estimated student proficiency level on a 1–4 scale"
    )
    student_changed_problem: bool = Field(
        description="True if the student changed the original problem, and moves on to solve something else."
    )
    
class StudentJudge(MyAgent):
    """Judge for the student's abstraction level and topic consistency."""

    def _agent_constructor(self):
        model = ChatOpenAI(
            model=self.model_name,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        agent_judge = create_agent(
            model=model,
            tools=None,
            response_format=StudentJudgeOutput,
        )
        return agent_judge

class TutorJudgeOutput(BaseModel):
    tutor_level_explanation: str = Field(
        description="Explain why you chose the value for the tutor level field."
    )
    tutor_level: int = Field(
        ge=1,
        le=4,
        description="Estimated tutor abstraction level on a 1–4 scale"
    )
    leakage_explanation: str = Field(
        description="Explain why leakage was or was not detected."
    )
    leakage_detected: bool = Field(
        description="True if the tutor reveals the final answer or gives away a key solution step."
    )

class TutorJudge(MyAgent):
    """Judge for tutor abstraction and solution leakage."""

    def invoke(self, message: AIMessage) -> AIMessage:
        """
        Judge receives an AIMessage from the Tutor and responds with an AIMessage.
        """
        # avoid referring to TutorJudge by name, which could raise NameError in some contexts
        ai_response = super().invoke(HumanMessage(content=message.content))
        return ai_response

    def invoke_pprint(self, message: AIMessage) -> AIMessage:
        out = self.invoke(message=message)
        pprint(out.content)
        return out

    def _agent_constructor(self):
        model = ChatOpenAI(
            model=self.model_name,
            timeout=self.request_timeout_seconds,
            max_retries=self.max_retries,
        )
        agent_judge = create_agent(
            model=model,
            tools=None,
            response_format=TutorJudgeOutput,
        )
        return agent_judge
